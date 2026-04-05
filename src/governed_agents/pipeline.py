"""Governance pipeline for multi-handler enforcement.

Implements the middleware chain pattern supporting:
- Priority-ordered handler groups
- Mixed parallel/sequential execution within groups
- Graceful degradation (handler failures logged, not propagated)
- Context modification chaining (sequential handlers can transform context)
- Block short-circuiting (any handler can halt the pipeline)

Handler dependency graph example:
    Priority 10 (parallel):  PIIFilter + RateLimiter
    Priority 20 (sequential): GovernanceCheck
    Priority 30 (parallel):  AuditLogger + MetricsCollector
    Priority 40 (sequential): ComplianceChecker
"""

from __future__ import annotations

import asyncio
import logging

from governed_agents.handler import (
    ActionContext,
    ExecutionMode,
    GovernanceHandler,
    GovernanceResult,
    HandlerRegistration,
    Verdict,
)

logger = logging.getLogger(__name__)


class GovernancePipeline:
    """Ordered middleware chain for governance evaluation.

    Supports mixed sequential/parallel execution:
    - Handlers are grouped by priority level.
    - Within a group, if ALL handlers are PARALLEL, they fan out concurrently.
    - Otherwise, handlers run sequentially in registration order.
    - Any handler returning BLOCK halts the entire pipeline.
    - Handlers returning MODIFY transform the context for downstream handlers.

    Graceful degradation:
    - Handler exceptions are logged as warnings, not propagated.
    - Optional handlers (audit, metrics) are skipped on failure.
    - Non-optional handler failures are treated as BLOCK with a warning.
    """

    def __init__(self) -> None:
        self._registrations: list[HandlerRegistration] = []

    def register(
        self,
        handler: GovernanceHandler,
        priority: int = 100,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        optional: bool = False,
        depends_on: frozenset[str] | None = None,
    ) -> None:
        """Register a handler in the pipeline with explicit priority.

        Args:
            handler: The handler to register.
            priority: Execution order group (lower runs first).
            mode: Sequential or parallel execution.
            optional: If True, failure does not affect the pipeline verdict.
            depends_on: Handler names that must complete before this handler runs.
        """
        self._registrations.append(
            HandlerRegistration(
                handler=handler,
                priority=priority,
                mode=mode,
                optional=optional,
                depends_on=depends_on or frozenset(),
            )
        )
        # Keep sorted by priority for deterministic execution
        self._registrations.sort(key=lambda r: r.priority)

    def add(
        self,
        handler: GovernanceHandler,
        *,
        optional: bool = False,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    ) -> None:
        """Add a handler with auto-assigned priority.

        Priority is auto-incremented by 10 from the last registered handler's
        priority, starting at 10 if the pipeline is empty.

        Args:
            handler: The handler to add.
            optional: If True, failure does not affect the pipeline verdict.
            mode: Sequential or parallel execution.
        """
        if self._registrations:
            last_priority = self._registrations[-1].priority
            priority = last_priority + 10
        else:
            priority = 10

        self.register(handler, priority=priority, mode=mode, optional=optional)

    @property
    def handlers(self) -> list[HandlerRegistration]:
        """Return the registered handlers in priority order."""
        return list(self._registrations)

    def _group_by_priority(self) -> list[tuple[int, list[HandlerRegistration]]]:
        """Group handlers by priority level.

        Returns:
            List of (priority, handlers) tuples, sorted by priority.
        """
        groups: dict[int, list[HandlerRegistration]] = {}
        for reg in self._registrations:
            groups.setdefault(reg.priority, []).append(reg)
        return sorted(groups.items(), key=lambda x: x[0])

    async def execute(self, context: ActionContext) -> GovernanceResult:
        """Execute the pipeline against the given context.

        Processes handlers group-by-group in priority order:
        1. Validates depends_on: handlers whose dependencies haven't completed
           in a prior group are deferred to the next group.
        2. All-parallel groups fan out concurrently via asyncio.gather.
        3. Sequential groups run handlers one at a time.
        4. BLOCK from any handler halts the pipeline immediately.
        5. MODIFY updates the context for downstream handlers.
        6. Exceptions are caught and logged (graceful degradation).

        Args:
            context: The action context to evaluate.

        Returns:
            Final GovernanceResult -- ALLOW if all passed, or the first BLOCK.
        """
        groups = self._group_by_priority()
        completed_handlers: set[str] = set()

        for idx, (priority, group) in enumerate(groups):
            # Separate handlers whose dependencies are satisfied vs deferred
            ready: list[HandlerRegistration] = []
            deferred: list[HandlerRegistration] = []

            for reg in group:
                unmet = reg.depends_on - completed_handlers
                if unmet:
                    logger.info(
                        "Handler '%s' deferred from priority %d: "
                        "unmet dependencies %s",
                        reg.handler.name,
                        priority,
                        unmet,
                    )
                    deferred.append(reg)
                else:
                    ready.append(reg)

            # Inject deferred handlers into the next group
            if deferred:
                if idx + 1 < len(groups):
                    next_priority, next_group = groups[idx + 1]
                    next_group.extend(deferred)
                else:
                    # No next group -- create a synthetic trailing group
                    groups.append((priority + 1, deferred))

            if not ready:
                continue

            all_parallel = all(r.mode == ExecutionMode.PARALLEL for r in ready)

            if all_parallel and len(ready) > 1:
                # Fan out concurrently
                result = await self._execute_parallel(ready, context)
            else:
                # Sequential execution
                result = await self._execute_sequential(ready, context)

            # Track completed handler names
            for reg in ready:
                completed_handlers.add(reg.handler.name)

            if result is None:
                continue

            if result.action == Verdict.BLOCK:
                return result

            if result.action == Verdict.MODIFY and result.modified_context is not None:
                context = result.modified_context

        return GovernanceResult.continue_(reason="All handlers passed")

    async def _execute_parallel(
        self,
        group: list[HandlerRegistration],
        context: ActionContext,
    ) -> GovernanceResult | None:
        """Execute a parallel group of handlers concurrently.

        Returns the first BLOCK result, or the last MODIFY, or None if all ALLOW.
        """
        tasks = [self._safe_check(reg, context) for reg in group]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        last_modify: GovernanceResult | None = None

        for result in results:
            if result is None:
                continue
            if result.action == Verdict.BLOCK:
                return result
            if result.action == Verdict.MODIFY:
                last_modify = result

        return last_modify

    async def _execute_sequential(
        self,
        group: list[HandlerRegistration],
        context: ActionContext,
    ) -> GovernanceResult | None:
        """Execute a sequential group of handlers one at a time.

        Context modifications are chained: each MODIFY updates the context
        for the next handler in the group.

        Returns the first BLOCK result, or the last MODIFY, or None if all ALLOW.
        """
        last_modify: GovernanceResult | None = None

        for reg in group:
            result = await self._safe_check(reg, context)
            if result is None:
                continue
            if result.action == Verdict.BLOCK:
                return result
            if result.action == Verdict.MODIFY and result.modified_context is not None:
                context = result.modified_context
                last_modify = result

        return last_modify

    async def _safe_check(
        self,
        reg: HandlerRegistration,
        context: ActionContext,
    ) -> GovernanceResult | None:
        """Execute a single handler with graceful degradation.

        Catches exceptions and logs them. Optional handlers return None on failure.
        Non-optional handler failures block the pipeline to prevent silent bypass.
        """
        try:
            return await reg.handler.evaluate(context)
        except Exception:
            if reg.optional:
                logger.warning(
                    "Optional handler '%s' failed (skipped): ",
                    reg.handler.name,
                    exc_info=True,
                )
                return None
            else:
                logger.error(
                    "Non-optional handler '%s' failed -- blocking pipeline: ",
                    reg.handler.name,
                    exc_info=True,
                )
                return GovernanceResult.abort(
                    handler_name=reg.handler.name,
                    reason=f"Handler '{reg.handler.name}' raised an exception",
                )


# Backward-compatible alias (not exported in __init__.py)
CallbackPipeline = GovernancePipeline
