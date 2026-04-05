"""Recovery executor -- stateful governance with automatic recovery.

# Layer: Dynamic (stateful, drives recovery workflows)

Wraps a GovernancePipeline and automatically executes recovery strategies
when actions are blocked. Instead of returning dead suggestions, the
executor ACTS: waits for delays, requests approval, retries with lower
scope, or delegates to human.

This is the difference between a governance library that CHECKS things
and one that DOES things.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable

from governed_agents.approval import (
    ApprovalBackend,
    ApprovalRequest,
    ApprovalStatus,
)
from governed_agents.handler import ActionContext, GovernanceResult, Verdict
from governed_agents.pipeline import GovernancePipeline
from governed_agents.recovery import RecoveryAction, RecoveryPlan

logger = logging.getLogger(__name__)


@dataclass
class RecoveryOutcome:
    """Result of recovery-aware execution."""

    final_result: GovernanceResult
    attempts: int  # How many pipeline evaluations
    recovery_actions_taken: list[RecoveryAction] = field(default_factory=list)
    approved_by: str = ""  # Who approved (if approval was obtained)

    @property
    def succeeded(self) -> bool:
        """Did the action ultimately pass governance?"""
        return self.final_result.action != Verdict.BLOCK


class RecoveryExecutor:
    """Executes governance with automatic recovery on block.

    Instead of::

        result = await pipeline.execute(ctx)
        if result.action == Verdict.BLOCK:
            print(result.suggestion)  # Dead string

    Use::

        executor = RecoveryExecutor(pipeline)
        outcome = await executor.execute(ctx)
        # Executor automatically attempted recovery strategies
        # outcome.succeeded tells you if it worked

    Recovery strategies executed automatically:

    - RETRY_AFTER_DELAY: sleeps for the specified duration, then retries
    - RETRY_WITH_APPROVAL: calls ApprovalBackend, waits, retries with approval
    - RETRY_LOWER_SCOPE: removes high-risk payload fields, retries
    - USE_CHEAPER_RESOURCE: sets metadata flag for cheaper model, retries
    - DOWNGRADE_TO_ADVISORY: lowers VT tier and marks as advisory, retries
    - DELEGATE_TO_HUMAN, BATCH_WITH_OTHERS, SPLIT_ACTION: not auto-executed
      (these require external coordination; reported in outcome)

    Args:
        pipeline: The governance pipeline to execute.
        approval_backend: Optional backend for VT2+ approval workflows.
        max_retries: Maximum recovery attempts before giving up.
        max_delay_seconds: Maximum delay for RETRY_AFTER_DELAY (safety cap).
        on_recovery: Optional callback invoked when recovery is attempted.
    """

    def __init__(
        self,
        pipeline: GovernancePipeline,
        approval_backend: ApprovalBackend | None = None,
        max_retries: int = 3,
        max_delay_seconds: float = 60.0,
        on_recovery: (Callable[[RecoveryAction, ActionContext], Awaitable[None]] | None) = None,
    ) -> None:
        self._pipeline = pipeline
        self._approval = approval_backend
        self._max_retries = max_retries
        self._max_delay = max_delay_seconds
        self._on_recovery = on_recovery

    async def execute(self, context: ActionContext) -> RecoveryOutcome:
        """Execute the pipeline with automatic recovery on block."""
        actions_taken: list[RecoveryAction] = []
        current_ctx = context
        approved_by = ""

        for attempt in range(1, self._max_retries + 2):  # +1 initial, +1 fence
            result = await self._pipeline.execute(current_ctx)

            # If not blocked, we're done
            if result.action != Verdict.BLOCK:
                return RecoveryOutcome(
                    final_result=result,
                    attempts=attempt,
                    recovery_actions_taken=actions_taken,
                    approved_by=approved_by,
                )

            # No recovery plan or max retries reached
            if result.recovery is None or attempt > self._max_retries:
                return RecoveryOutcome(
                    final_result=result,
                    attempts=attempt,
                    recovery_actions_taken=actions_taken,
                )

            # Try to execute the primary recovery action
            recovery = result.recovery
            action = recovery.primary

            new_ctx, who = await self._execute_recovery(action, current_ctx, recovery)

            if new_ctx is None:
                # Primary failed -- try alternatives
                executed = False
                for alt in recovery.alternatives:
                    new_ctx, who = await self._execute_recovery(alt, current_ctx, recovery)
                    if new_ctx is not None:
                        action = alt
                        executed = True
                        break

                if not executed:
                    # No recovery action could be executed automatically
                    return RecoveryOutcome(
                        final_result=result,
                        attempts=attempt,
                        recovery_actions_taken=actions_taken,
                    )

            if who:
                approved_by = who

            actions_taken.append(action)

            if self._on_recovery:
                await self._on_recovery(action, new_ctx)

            logger.info(
                "RecoveryExecutor: attempt %d, action=%s, recovery=%s",
                attempt,
                current_ctx.action,
                action.value,
            )

            current_ctx = new_ctx

        # Safety: should not normally reach here
        result = await self._pipeline.execute(current_ctx)
        return RecoveryOutcome(
            final_result=result,
            attempts=self._max_retries + 1,
            recovery_actions_taken=actions_taken,
        )

    async def _execute_recovery(
        self,
        action: RecoveryAction,
        ctx: ActionContext,
        plan: RecoveryPlan,
    ) -> tuple[ActionContext | None, str]:
        """Execute a recovery action.

        Returns (modified_context, approver_id) or (None, "") if
        the action cannot be auto-executed.
        """

        if action == RecoveryAction.RETRY_AFTER_DELAY:
            delay = min(
                plan.context.get("delay_seconds", 5.0),
                self._max_delay,
            )
            await asyncio.sleep(delay)
            return ctx, ""  # Same context, just delayed

        if action == RecoveryAction.RETRY_WITH_APPROVAL:
            if self._approval is None:
                return None, ""  # No approval backend configured

            trace_id = f"recovery-{uuid.uuid4().hex[:8]}"
            request = ApprovalRequest(
                trace_id=trace_id,
                action=ctx.action,
                agent_id=ctx.agent_id,
                vt_tier=ctx.vt_tier,
                summary=f"Recovery: approve '{ctx.action}' by '{ctx.agent_id}'",
            )
            await self._approval.request_approval(request)

            # Poll for approval (with timeout from plan context)
            timeout = plan.context.get("timeout_seconds", 30)
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout

            while loop.time() < deadline:
                response = await self._approval.check_approval(trace_id)
                if response is not None:
                    if response.status == ApprovalStatus.APPROVED:
                        new_meta = {**ctx.metadata, "vt2_approved": True}
                        return (
                            replace(ctx, metadata=new_meta),
                            response.responded_by,
                        )
                    if response.status == ApprovalStatus.DENIED:
                        return None, ""
                    if response.status == ApprovalStatus.DEFERRED:
                        return None, ""
                await asyncio.sleep(0.5)

            # Timeout
            await self._approval.cancel_approval(trace_id)
            return None, ""

        if action == RecoveryAction.RETRY_LOWER_SCOPE:
            pii_fields = plan.context.get("pii_fields", [])
            high_risk = plan.context.get("high_risk_fields", [])
            drop = set(pii_fields) | set(high_risk)
            lower_payload = {k: v for k, v in ctx.payload.items() if k not in drop}
            return replace(ctx, payload=lower_payload), ""

        if action == RecoveryAction.USE_CHEAPER_RESOURCE:
            new_meta = {**ctx.metadata, "use_cheaper_model": True}
            estimated = ctx.metadata.get("estimated_cost_usd", 0)
            if estimated > 0:
                new_meta["estimated_cost_usd"] = estimated * 0.3
            return replace(ctx, metadata=new_meta), ""

        if action == RecoveryAction.DOWNGRADE_TO_ADVISORY:
            new_meta = {**ctx.metadata, "advisory_only": True}
            new_vt = max(0, ctx.vt_tier - 1)
            return replace(ctx, vt_tier=new_vt, metadata=new_meta), ""

        # DELEGATE_TO_HUMAN, BATCH_WITH_OTHERS, SPLIT_ACTION
        # These require external coordination and can't be auto-executed
        return None, ""
