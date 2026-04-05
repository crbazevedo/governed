"""Governance pipeline for multi-handler enforcement.

# Layer: Static (stateless orchestration -- state lives in handlers)

Implements the middleware chain pattern supporting:
- Priority-ordered handler groups
- Mixed parallel/sequential execution within groups
- Graceful degradation (handler failures logged, not propagated)
- Context modification chaining (sequential handlers can transform context)
- Block short-circuiting (any handler can halt the pipeline)
- Execution tracing for introspection and debugging

Handler dependency graph example:
    Priority 10 (parallel):  PIIFilter + RateLimiter
    Priority 20 (sequential): GovernanceCheck
    Priority 30 (parallel):  AuditLogger + MetricsCollector
    Priority 40 (sequential): ComplianceChecker
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from governed_agents.handler import (
    ActionContext,
    ExecutionMode,
    GovernanceHandler,
    GovernanceResult,
    HandlerRegistration,
    Verdict,
)
from governed_agents.recovery import RecoveryAction, RecoveryPlan

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Execution trace types
# ──────────────────────────────────────────────


@dataclass
class HandlerTrace:
    """Record of a single handler execution within the pipeline.

    Captures the handler's verdict, timing, and recovery guidance --
    enabling post-hoc analysis of why a pipeline reached its final verdict.
    """

    handler_name: str
    verdict: Verdict
    reason: str
    duration_ms: float
    suggestion: str = ""
    alternatives: list[str] = field(default_factory=list)


@dataclass
class ExecutionTrace:
    """Full trace of a pipeline execution.

    Provides complete introspection into what happened during a pipeline run:
    which handlers ran, what each decided, how long each took, and what
    recovery guidance is available.  This enables observability dashboards,
    debugging, and automated recovery logic.
    """

    final_verdict: Verdict
    final_reason: str
    handler_traces: list[HandlerTrace]
    total_duration_ms: float
    context_modifications: int
    suggestion: str = ""
    alternatives: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Human-readable one-line summary of the execution."""
        handlers = ", ".join(h.handler_name for h in self.handler_traces)
        return (
            f"{self.final_verdict.value} "
            f"({self.total_duration_ms:.1f}ms, "
            f"{len(self.handler_traces)} handlers: {handlers})"
        )


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
        result, _, _ = await self._execute_internal(context)
        return result

    async def execute_traced(self, context: ActionContext) -> ExecutionTrace:
        """Execute the pipeline and return a full execution trace.

        Same semantics as ``execute()``, but returns an ``ExecutionTrace``
        capturing per-handler timing, verdicts, and recovery guidance.
        Use this for observability, debugging, or automated recovery logic.

        Args:
            context: The action context to evaluate.

        Returns:
            ExecutionTrace with the final verdict and per-handler details.
        """
        _, trace, _ = await self._execute_internal(context)
        return trace

    async def execute_with_context(
        self, context: ActionContext
    ) -> tuple[GovernanceResult, ActionContext]:
        """Execute the pipeline and return both the result and final context.

        Unlike ``execute()``, this method returns the (possibly modified)
        context after all handlers have run.  Use this when you need to
        access the transformed payload (e.g. after PII redaction).

        Args:
            context: The action context to evaluate.

        Returns:
            Tuple of (GovernanceResult, final ActionContext).
        """
        result, _, final_ctx = await self._execute_internal(context)
        return result, final_ctx

    async def _execute_internal(
        self, context: ActionContext
    ) -> tuple[GovernanceResult, ExecutionTrace, ActionContext]:
        """Core pipeline execution with tracing.

        Returns the GovernanceResult, ExecutionTrace, and the final
        (possibly modified) ActionContext.
        """
        pipeline_start = time.perf_counter_ns()
        handler_traces: list[HandlerTrace] = []
        context_modifications = 0

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
                        "Handler '%s' deferred from priority %d: unmet dependencies %s",
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
                result = await self._execute_parallel_traced(ready, context, handler_traces)
            else:
                result = await self._execute_sequential_traced(ready, context, handler_traces)

            # Track completed handler names
            for reg in ready:
                completed_handlers.add(reg.handler.name)

            if result is None:
                continue

            if result.action == Verdict.BLOCK:
                total_ms = (time.perf_counter_ns() - pipeline_start) / 1_000_000
                trace = ExecutionTrace(
                    final_verdict=Verdict.BLOCK,
                    final_reason=result.reason,
                    handler_traces=handler_traces,
                    total_duration_ms=total_ms,
                    context_modifications=context_modifications,
                    suggestion=result.suggestion,
                    alternatives=list(result.alternatives),
                )
                return result, trace, context

            if result.action == Verdict.MODIFY and result.modified_context is not None:
                context = result.modified_context
                context_modifications += 1

        final = GovernanceResult.continue_(reason="All handlers passed")
        total_ms = (time.perf_counter_ns() - pipeline_start) / 1_000_000
        trace = ExecutionTrace(
            final_verdict=Verdict.ALLOW,
            final_reason=final.reason,
            handler_traces=handler_traces,
            total_duration_ms=total_ms,
            context_modifications=context_modifications,
        )
        return final, trace, context

    async def _execute_parallel_traced(
        self,
        group: list[HandlerRegistration],
        context: ActionContext,
        handler_traces: list[HandlerTrace],
    ) -> GovernanceResult | None:
        """Execute a parallel group concurrently, recording traces."""
        tasks = [self._safe_check_traced(reg, context) for reg in group]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        last_modify: GovernanceResult | None = None

        for result, htrace in results:
            handler_traces.append(htrace)
            if result is None:
                continue
            if result.action == Verdict.BLOCK:
                return result
            if result.action == Verdict.MODIFY:
                last_modify = result

        return last_modify

    async def _execute_sequential_traced(
        self,
        group: list[HandlerRegistration],
        context: ActionContext,
        handler_traces: list[HandlerTrace],
    ) -> GovernanceResult | None:
        """Execute a sequential group one at a time, recording traces."""
        last_modify: GovernanceResult | None = None

        for reg in group:
            result, htrace = await self._safe_check_traced(reg, context)
            handler_traces.append(htrace)
            if result is None:
                continue
            if result.action == Verdict.BLOCK:
                return result
            if result.action == Verdict.MODIFY and result.modified_context is not None:
                context = result.modified_context
                last_modify = result

        return last_modify

    async def _safe_check_traced(
        self,
        reg: HandlerRegistration,
        context: ActionContext,
    ) -> tuple[GovernanceResult | None, HandlerTrace]:
        """Execute a handler with tracing and graceful degradation."""
        start_ns = time.perf_counter_ns()
        result = await self._safe_check(reg, context)
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        if result is None:
            htrace = HandlerTrace(
                handler_name=reg.handler.name,
                verdict=Verdict.ALLOW,
                reason="skipped (optional handler failed)",
                duration_ms=elapsed_ms,
            )
        else:
            htrace = HandlerTrace(
                handler_name=reg.handler.name,
                verdict=result.action,
                reason=result.reason,
                duration_ms=elapsed_ms,
                suggestion=result.suggestion,
                alternatives=list(result.alternatives),
            )

        return result, htrace

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
                    suggestion="Check handler logs for the exception traceback and fix the handler",
                    alternatives=[
                        "Mark the handler as optional if it should not block the pipeline"
                    ],
                    recovery=RecoveryPlan(
                        primary=RecoveryAction.DELEGATE_TO_HUMAN,
                        explanation=f"Handler '{reg.handler.name}' crashed unexpectedly",
                    ),
                )


# Backward-compatible alias (not exported in __init__.py)
CallbackPipeline = GovernancePipeline
