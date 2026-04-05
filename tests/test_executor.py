"""Tests for RecoveryExecutor -- stateful recovery state machine.

Validates that the executor automatically attempts recovery strategies
when the governance pipeline blocks an action, instead of returning
dead suggestions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from governed_agents import ActionContext, GovernancePipeline, GovernanceResult, Verdict
from governed_agents.approval import (
    ApprovalBackend,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
)
from governed_agents.executor import RecoveryExecutor
from governed_agents.handler import GovernanceHandler
from governed_agents.recovery import RecoveryAction, RecoveryPlan


# ── Helpers ────────────────────────────────────────────────


class AlwaysAllow(GovernanceHandler):
    """Handler that always allows."""

    @property
    def name(self) -> str:
        return "always_allow"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        return GovernanceResult.continue_(handler_name=self.name)


class AlwaysBlock(GovernanceHandler):
    """Handler that always blocks, with optional recovery plan."""

    def __init__(self, recovery: RecoveryPlan | None = None):
        self._recovery = recovery

    @property
    def name(self) -> str:
        return "always_block"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        return GovernanceResult.abort(
            handler_name=self.name,
            reason="Blocked for testing",
            recovery=self._recovery,
        )


class BlockThenAllow(GovernanceHandler):
    """Blocks the first N calls, then allows."""

    def __init__(self, block_count: int = 1, recovery: RecoveryPlan | None = None):
        self._block_count = block_count
        self._calls = 0
        self._recovery = recovery

    @property
    def name(self) -> str:
        return "block_then_allow"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        self._calls += 1
        if self._calls <= self._block_count:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Blocked (call {self._calls})",
                recovery=self._recovery,
            )
        return GovernanceResult.continue_(handler_name=self.name)


class ConditionalHandler(GovernanceHandler):
    """Blocks based on a condition on the context."""

    def __init__(self, block_if_key: str, recovery: RecoveryPlan | None = None):
        self._block_key = block_if_key
        self._recovery = recovery

    @property
    def name(self) -> str:
        return "conditional"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if self._block_key in context.payload:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Blocked: payload contains '{self._block_key}'",
                recovery=self._recovery,
            )
        return GovernanceResult.continue_(handler_name=self.name)


class VTCheckHandler(GovernanceHandler):
    """Blocks if vt_tier >= threshold."""

    def __init__(self, threshold: int = 2, recovery: RecoveryPlan | None = None):
        self._threshold = threshold
        self._recovery = recovery

    @property
    def name(self) -> str:
        return "vt_check"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if context.vt_tier >= self._threshold:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"VT{context.vt_tier} >= threshold VT{self._threshold}",
                recovery=self._recovery,
            )
        return GovernanceResult.continue_(handler_name=self.name)


class MetadataCheckHandler(GovernanceHandler):
    """Blocks unless metadata has a specific key set to True."""

    def __init__(self, key: str, recovery: RecoveryPlan | None = None):
        self._key = key
        self._recovery = recovery

    @property
    def name(self) -> str:
        return "metadata_check"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if context.metadata.get(self._key):
            return GovernanceResult.continue_(handler_name=self.name)
        return GovernanceResult.abort(
            handler_name=self.name,
            reason=f"Blocked: missing metadata['{self._key}']",
            recovery=self._recovery,
        )


class FakeApprovalBackend(ApprovalBackend):
    """In-memory approval backend for testing."""

    def __init__(self, auto_response: ApprovalResponse | None = None):
        self._auto = auto_response
        self._requests: list[ApprovalRequest] = []
        self._cancelled: list[str] = []

    async def request_approval(self, request: ApprovalRequest) -> None:
        self._requests.append(request)

    async def check_approval(self, trace_id: str) -> ApprovalResponse | None:
        return self._auto

    async def cancel_approval(self, trace_id: str) -> None:
        self._cancelled.append(trace_id)


# ── Test 1: Action ALLOWED on first try ───────────────────


class TestAllowOnFirstTry:
    async def test_allowed_immediately(self):
        pipeline = GovernancePipeline()
        pipeline.add(AlwaysAllow())
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="read", agent_id="bot", vt_tier=0)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 1
        assert outcome.recovery_actions_taken == []

    async def test_allowed_result_preserved(self):
        pipeline = GovernancePipeline()
        pipeline.add(AlwaysAllow())
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="read", agent_id="bot", vt_tier=0)

        outcome = await executor.execute(ctx)

        assert outcome.final_result.action == Verdict.ALLOW


# ── Test 2: BLOCKED with no recovery plan ─────────────────


class TestBlockedNoRecovery:
    async def test_blocked_without_plan(self):
        pipeline = GovernancePipeline()
        pipeline.add(AlwaysBlock(recovery=None))
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="delete", agent_id="bot", vt_tier=4)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is False
        assert outcome.attempts == 1
        assert outcome.recovery_actions_taken == []

    async def test_blocked_result_preserved(self):
        pipeline = GovernancePipeline()
        pipeline.add(AlwaysBlock(recovery=None))
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="delete", agent_id="bot", vt_tier=4)

        outcome = await executor.execute(ctx)

        assert outcome.final_result.action == Verdict.BLOCK
        assert "Blocked for testing" in outcome.final_result.reason


# ── Test 3: RETRY_AFTER_DELAY ─────────────────────────────


class TestRetryAfterDelay:
    async def test_delay_then_allow(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.5},
        )
        handler = BlockThenAllow(block_count=1, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline, max_delay_seconds=5.0)
        ctx = ActionContext(action="send", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            outcome = await executor.execute(ctx)
            mock_sleep.assert_called_once_with(0.5)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        assert RecoveryAction.RETRY_AFTER_DELAY in outcome.recovery_actions_taken

    async def test_delay_capped_at_max(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 999.0},
        )
        handler = BlockThenAllow(block_count=1, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline, max_delay_seconds=10.0)
        ctx = ActionContext(action="send", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            outcome = await executor.execute(ctx)
            mock_sleep.assert_called_once_with(10.0)

        assert outcome.succeeded is True


# ── Test 4: RETRY_LOWER_SCOPE ─────────────────────────────


class TestRetryLowerScope:
    async def test_remove_pii_fields_then_allow(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_LOWER_SCOPE,
            context={"pii_fields": ["email"]},
        )
        handler = ConditionalHandler(block_if_key="email", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(
            action="process",
            agent_id="bot",
            vt_tier=1,
            payload={"email": "user@example.com", "query": "search"},
        )

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        assert RecoveryAction.RETRY_LOWER_SCOPE in outcome.recovery_actions_taken

    async def test_remove_high_risk_fields(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_LOWER_SCOPE,
            context={"high_risk_fields": ["ssn"]},
        )
        handler = ConditionalHandler(block_if_key="ssn", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(
            action="process",
            agent_id="bot",
            vt_tier=1,
            payload={"ssn": "123-45-6789", "name": "Test"},
        )

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2


# ── Test 5: USE_CHEAPER_RESOURCE ───────────────────────────


class TestUseCheaperResource:
    async def test_cheaper_resource_then_allow(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.USE_CHEAPER_RESOURCE,
        )
        # Handler blocks unless use_cheaper_model is set
        handler = MetadataCheckHandler(key="use_cheaper_model", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(
            action="generate",
            agent_id="bot",
            vt_tier=1,
            metadata={"estimated_cost_usd": 10.0},
        )

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        assert RecoveryAction.USE_CHEAPER_RESOURCE in outcome.recovery_actions_taken

    async def test_cheaper_resource_adjusts_cost(self):
        recovery = RecoveryPlan(primary=RecoveryAction.USE_CHEAPER_RESOURCE)

        # Track the context that arrives after recovery
        seen_contexts: list[ActionContext] = []

        class SpyHandler(GovernanceHandler):
            @property
            def name(self):
                return "spy"

            async def evaluate(self, context):
                seen_contexts.append(context)
                if not context.metadata.get("use_cheaper_model"):
                    return GovernanceResult.abort(
                        handler_name=self.name,
                        reason="Too expensive",
                        recovery=recovery,
                    )
                return GovernanceResult.continue_(handler_name=self.name)

        pipeline = GovernancePipeline()
        pipeline.add(SpyHandler())
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(
            action="generate",
            agent_id="bot",
            vt_tier=1,
            metadata={"estimated_cost_usd": 10.0},
        )

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        # Second call should have reduced cost
        assert seen_contexts[1].metadata["estimated_cost_usd"] == pytest.approx(3.0)
        assert seen_contexts[1].metadata["use_cheaper_model"] is True


# ── Test 6: DOWNGRADE_TO_ADVISORY ──────────────────────────


class TestDowngradeToAdvisory:
    async def test_downgrade_vt_then_allow(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.DOWNGRADE_TO_ADVISORY,
        )
        # Handler blocks VT >= 2
        handler = VTCheckHandler(threshold=2, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="deploy", agent_id="eng", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        assert RecoveryAction.DOWNGRADE_TO_ADVISORY in outcome.recovery_actions_taken

    async def test_downgrade_sets_advisory_flag(self):
        recovery = RecoveryPlan(primary=RecoveryAction.DOWNGRADE_TO_ADVISORY)

        seen: list[ActionContext] = []

        class SpyHandler(GovernanceHandler):
            @property
            def name(self):
                return "spy"

            async def evaluate(self, context):
                seen.append(context)
                if context.vt_tier >= 3:
                    return GovernanceResult.abort(
                        handler_name=self.name,
                        reason="VT3 blocked",
                        recovery=recovery,
                    )
                return GovernanceResult.continue_(handler_name=self.name)

        pipeline = GovernancePipeline()
        pipeline.add(SpyHandler())
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="deploy", agent_id="eng", vt_tier=3)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert seen[1].vt_tier == 2
        assert seen[1].metadata.get("advisory_only") is True

    async def test_downgrade_floors_at_vt0(self):
        recovery = RecoveryPlan(primary=RecoveryAction.DOWNGRADE_TO_ADVISORY)

        seen: list[ActionContext] = []

        class SpyHandler(GovernanceHandler):
            call_count = 0

            @property
            def name(self):
                return "spy"

            async def evaluate(self, context):
                self.call_count += 1
                seen.append(context)
                # Only block the first call
                if self.call_count == 1:
                    return GovernanceResult.abort(
                        handler_name=self.name,
                        reason="Blocked",
                        recovery=recovery,
                    )
                return GovernanceResult.continue_(handler_name=self.name)

        pipeline = GovernancePipeline()
        pipeline.add(SpyHandler())
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="read", agent_id="bot", vt_tier=0)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        # VT0 downgraded stays at 0 (can't go below)
        assert seen[1].vt_tier == 0


# ── Test 7: RETRY_WITH_APPROVAL (approved) ─────────────────


class TestRetryWithApprovalApproved:
    async def test_approval_granted(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            context={"timeout_seconds": 5},
        )
        # Handler blocks unless vt2_approved
        handler = MetadataCheckHandler(key="vt2_approved", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        backend = FakeApprovalBackend(
            auto_response=ApprovalResponse(
                trace_id="test",
                status=ApprovalStatus.APPROVED,
                responded_by="owner",
            )
        )
        executor = RecoveryExecutor(pipeline, approval_backend=backend)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        assert RecoveryAction.RETRY_WITH_APPROVAL in outcome.recovery_actions_taken
        assert outcome.approved_by == "owner"
        assert len(backend._requests) == 1

    async def test_approval_no_backend_cannot_recover(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
        )
        handler = MetadataCheckHandler(key="vt2_approved", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        executor = RecoveryExecutor(pipeline, approval_backend=None)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is False


# ── Test 8: RETRY_WITH_APPROVAL (denied) ───────────────────


class TestRetryWithApprovalDenied:
    async def test_approval_denied(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            context={"timeout_seconds": 5},
        )
        handler = MetadataCheckHandler(key="vt2_approved", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        backend = FakeApprovalBackend(
            auto_response=ApprovalResponse(
                trace_id="test",
                status=ApprovalStatus.DENIED,
                responded_by="owner",
            )
        )
        executor = RecoveryExecutor(pipeline, approval_backend=backend)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is False
        assert outcome.recovery_actions_taken == []  # Primary failed, no alt

    async def test_approval_deferred(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            context={"timeout_seconds": 5},
        )
        handler = MetadataCheckHandler(key="vt2_approved", recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        backend = FakeApprovalBackend(
            auto_response=ApprovalResponse(
                trace_id="test",
                status=ApprovalStatus.DEFERRED,
            )
        )
        executor = RecoveryExecutor(pipeline, approval_backend=backend)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is False


# ── Test 9: Max retries exhausted ──────────────────────────


class TestMaxRetries:
    async def test_retries_exhausted(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.0},
        )
        # Always blocks (never allows), so retries exhaust
        handler = AlwaysBlock(recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline, max_retries=2)
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock):
            outcome = await executor.execute(ctx)

        assert outcome.succeeded is False
        # 2 retries + the attempt that exceeded max_retries
        assert outcome.attempts == 3
        assert len(outcome.recovery_actions_taken) == 2

    async def test_max_retries_one(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.0},
        )
        handler = AlwaysBlock(recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline, max_retries=1)
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock):
            outcome = await executor.execute(ctx)

        assert outcome.succeeded is False
        assert outcome.attempts == 2
        assert len(outcome.recovery_actions_taken) == 1


# ── Test 10: Primary fails, fallback to alternative ───────


class TestFallbackToAlternative:
    async def test_primary_delegate_falls_back_to_downgrade(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.DELEGATE_TO_HUMAN,  # Can't auto-execute
            alternatives=[RecoveryAction.DOWNGRADE_TO_ADVISORY],
        )
        # Blocks VT >= 2
        handler = VTCheckHandler(threshold=2, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="deploy", agent_id="eng", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert outcome.attempts == 2
        # Should have used the alternative, not the primary
        assert RecoveryAction.DOWNGRADE_TO_ADVISORY in outcome.recovery_actions_taken
        assert RecoveryAction.DELEGATE_TO_HUMAN not in outcome.recovery_actions_taken

    async def test_all_non_executable_recovery(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.DELEGATE_TO_HUMAN,
            alternatives=[
                RecoveryAction.BATCH_WITH_OTHERS,
                RecoveryAction.SPLIT_ACTION,
            ],
        )
        handler = AlwaysBlock(recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)
        executor = RecoveryExecutor(pipeline)
        ctx = ActionContext(action="deploy", agent_id="eng", vt_tier=2)

        outcome = await executor.execute(ctx)

        assert outcome.succeeded is False
        assert outcome.attempts == 1
        assert outcome.recovery_actions_taken == []


# ── Test 11: on_recovery callback ─────────────────────────


class TestOnRecoveryCallback:
    async def test_callback_called(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.0},
        )
        handler = BlockThenAllow(block_count=1, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        callback_calls: list[tuple[RecoveryAction, ActionContext]] = []

        async def on_recovery(action: RecoveryAction, ctx: ActionContext) -> None:
            callback_calls.append((action, ctx))

        executor = RecoveryExecutor(pipeline, on_recovery=on_recovery)
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock):
            outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == RecoveryAction.RETRY_AFTER_DELAY

    async def test_callback_called_multiple_times(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.0},
        )
        handler = BlockThenAllow(block_count=2, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        callback_calls: list[tuple[RecoveryAction, ActionContext]] = []

        async def on_recovery(action: RecoveryAction, ctx: ActionContext) -> None:
            callback_calls.append((action, ctx))

        executor = RecoveryExecutor(pipeline, on_recovery=on_recovery)
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock):
            outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
        assert len(callback_calls) == 2

    async def test_no_callback_when_not_set(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_AFTER_DELAY,
            context={"delay_seconds": 0.0},
        )
        handler = BlockThenAllow(block_count=1, recovery=recovery)
        pipeline = GovernancePipeline()
        pipeline.add(handler)

        executor = RecoveryExecutor(pipeline, on_recovery=None)
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=1)

        with patch("governed_agents.executor.asyncio.sleep", new_callable=AsyncMock):
            outcome = await executor.execute(ctx)

        assert outcome.succeeded is True
