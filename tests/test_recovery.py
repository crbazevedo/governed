"""Tests for the RecoveryAction protocol.

Validates typed, programmatic recovery plans attached to BLOCK verdicts
across all handlers: VT, Budget, RateLimiter, PIIFilter, AOW.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from governed_agents import ActionContext, Verdict
from governed_agents.aow import AOWHandler, AOWWindow
from governed_agents.decorator import GovernanceError, configure, reset_pipeline
from governed_agents.handler import GovernanceResult
from governed_agents.handlers import BudgetGatekeeper, PIIFilter, RateLimiter
from governed_agents.handlers.budget import ManualCostTracker
from governed_agents.recovery import RecoveryAction, RecoveryPlan
from governed_agents.vt import VTGovernanceHandler


# ── RecoveryAction enum ─────────────────────────────────────


class TestRecoveryAction:
    def test_enum_values(self):
        assert RecoveryAction.RETRY_WITH_APPROVAL == "retry_with_approval"
        assert RecoveryAction.RETRY_LOWER_SCOPE == "retry_lower_scope"
        assert RecoveryAction.RETRY_AFTER_DELAY == "retry_after_delay"
        assert RecoveryAction.DELEGATE_TO_HUMAN == "delegate_to_human"
        assert RecoveryAction.DOWNGRADE_TO_ADVISORY == "downgrade_to_advisory"
        assert RecoveryAction.BATCH_WITH_OTHERS == "batch_with_others"
        assert RecoveryAction.USE_CHEAPER_RESOURCE == "use_cheaper_resource"
        assert RecoveryAction.SPLIT_ACTION == "split_action"

    def test_string_representation(self):
        """RecoveryAction is a str enum, so str() and .value should match."""
        for action in RecoveryAction:
            assert str(action) == f"RecoveryAction.{action.name}"
            assert action.value == action.value  # identity
            # As a str subclass, can be used in string contexts
            assert action == action.value


# ── RecoveryPlan creation ────────────────────────────────────


class TestRecoveryPlan:
    def test_creation_primary_only(self):
        plan = RecoveryPlan(primary=RecoveryAction.DELEGATE_TO_HUMAN)
        assert plan.primary == RecoveryAction.DELEGATE_TO_HUMAN
        assert plan.alternatives == []
        assert plan.context == {}
        assert plan.explanation == ""

    def test_creation_with_alternatives(self):
        plan = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            alternatives=[
                RecoveryAction.DOWNGRADE_TO_ADVISORY,
                RecoveryAction.DELEGATE_TO_HUMAN,
            ],
        )
        assert plan.primary == RecoveryAction.RETRY_WITH_APPROVAL
        assert len(plan.alternatives) == 2

    def test_creation_with_context(self):
        plan = RecoveryPlan(
            primary=RecoveryAction.USE_CHEAPER_RESOURCE,
            context={"current_cost": 10.50, "limit": 5.0},
        )
        assert plan.context["current_cost"] == 10.50
        assert plan.context["limit"] == 5.0

    def test_has_primary(self):
        plan = RecoveryPlan(primary=RecoveryAction.DELEGATE_TO_HUMAN)
        assert plan.has(RecoveryAction.DELEGATE_TO_HUMAN) is True
        assert plan.has(RecoveryAction.RETRY_AFTER_DELAY) is False

    def test_has_alternative(self):
        plan = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            alternatives=[RecoveryAction.DOWNGRADE_TO_ADVISORY],
        )
        assert plan.has(RecoveryAction.DOWNGRADE_TO_ADVISORY) is True
        assert plan.has(RecoveryAction.SPLIT_ACTION) is False

    def test_all_actions_ordering(self):
        plan = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            alternatives=[
                RecoveryAction.DOWNGRADE_TO_ADVISORY,
                RecoveryAction.DELEGATE_TO_HUMAN,
            ],
        )
        actions = plan.all_actions
        assert actions[0] == RecoveryAction.RETRY_WITH_APPROVAL
        assert actions[1] == RecoveryAction.DOWNGRADE_TO_ADVISORY
        assert actions[2] == RecoveryAction.DELEGATE_TO_HUMAN
        assert len(actions) == 3

    def test_all_actions_primary_only(self):
        plan = RecoveryPlan(primary=RecoveryAction.DELEGATE_TO_HUMAN)
        assert plan.all_actions == [RecoveryAction.DELEGATE_TO_HUMAN]


# ── VTGovernanceHandler recovery plans ───────────────────────


class TestVTRecovery:
    async def test_vt2_block_produces_correct_recovery(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.RETRY_WITH_APPROVAL
        assert RecoveryAction.DOWNGRADE_TO_ADVISORY in result.recovery.alternatives
        assert RecoveryAction.DELEGATE_TO_HUMAN in result.recovery.alternatives

    async def test_vt3_block_produces_correct_recovery(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="deploy", agent_id="bot", vt_tier=3)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.DOWNGRADE_TO_ADVISORY
        assert result.recovery.alternatives == [RecoveryAction.DELEGATE_TO_HUMAN]

    async def test_vt4_block_produces_correct_recovery(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="delete_all", agent_id="bot", vt_tier=4)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.DELEGATE_TO_HUMAN
        assert result.recovery.alternatives == []

    async def test_vt0_allow_has_no_recovery(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="read_file", agent_id="bot", vt_tier=0)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW
        assert result.recovery is None

    async def test_vt1_modify_has_no_recovery(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="log_action", agent_id="bot", vt_tier=1)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.recovery is None


# ── BudgetGatekeeper recovery plans ──────────────────────────


class TestBudgetRecovery:
    async def test_budget_block_produces_correct_recovery(self):
        tracker = ManualCostTracker()
        tracker.add_cost(10.0)
        bg = BudgetGatekeeper(budget_limit_usd=5.0, cost_provider=tracker)
        ctx = ActionContext(action="test")
        result = await bg.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.USE_CHEAPER_RESOURCE
        assert RecoveryAction.BATCH_WITH_OTHERS in result.recovery.alternatives
        assert RecoveryAction.DELEGATE_TO_HUMAN in result.recovery.alternatives

    async def test_budget_block_recovery_has_cost_context(self):
        tracker = ManualCostTracker()
        tracker.add_cost(7.50)
        bg = BudgetGatekeeper(budget_limit_usd=5.0, cost_provider=tracker)
        ctx = ActionContext(action="test")
        result = await bg.evaluate(ctx)
        assert result.recovery is not None
        assert result.recovery.context["current_cost"] == 7.50
        assert result.recovery.context["limit"] == 5.0

    async def test_budget_allow_has_no_recovery(self):
        bg = BudgetGatekeeper(budget_limit_usd=100.0)
        ctx = ActionContext(action="test")
        result = await bg.evaluate(ctx)
        assert result.action == Verdict.ALLOW
        assert result.recovery is None


# ── RateLimiter recovery plans ───────────────────────────────


class TestRateLimiterRecovery:
    async def test_rate_limit_block_produces_correct_recovery(self):
        rl = RateLimiter(max_per_window=1, window_seconds=60)
        ctx = ActionContext(action="test", agent_id="bot")
        await rl.evaluate(ctx)  # First call OK
        result = await rl.evaluate(ctx)  # Second call blocked
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.RETRY_AFTER_DELAY
        assert RecoveryAction.BATCH_WITH_OTHERS in result.recovery.alternatives

    async def test_rate_limit_block_recovery_has_delay_seconds(self):
        rl = RateLimiter(max_per_window=1, window_seconds=30)
        ctx = ActionContext(action="test", agent_id="bot")
        await rl.evaluate(ctx)
        result = await rl.evaluate(ctx)
        assert result.recovery is not None
        assert "delay_seconds" in result.recovery.context
        assert isinstance(result.recovery.context["delay_seconds"], float)
        assert result.recovery.context["delay_seconds"] >= 0

    async def test_rate_limit_allow_has_no_recovery(self):
        rl = RateLimiter(max_per_window=10, window_seconds=60)
        ctx = ActionContext(action="test", agent_id="bot")
        result = await rl.evaluate(ctx)
        assert result.action == Verdict.ALLOW
        assert result.recovery is None


# ── PIIFilter recovery plans ─────────────────────────────────


class TestPIIFilterRecovery:
    async def test_pii_block_produces_correct_recovery(self):
        f = PIIFilter(redact=False)
        ctx = ActionContext(
            action="test",
            payload={"contact": "user@example.com", "data": "safe text"},
        )
        result = await f.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.RETRY_LOWER_SCOPE
        assert RecoveryAction.DELEGATE_TO_HUMAN in result.recovery.alternatives

    async def test_pii_block_recovery_has_pii_fields(self):
        f = PIIFilter(redact=False)
        ctx = ActionContext(
            action="test",
            payload={"email": "user@example.com", "notes": "safe"},
        )
        result = await f.evaluate(ctx)
        assert result.recovery is not None
        assert "pii_fields" in result.recovery.context
        assert isinstance(result.recovery.context["pii_fields"], list)
        assert len(result.recovery.context["pii_fields"]) > 0

    async def test_pii_redact_mode_has_no_recovery(self):
        """When redact=True, PII is modified not blocked, so no recovery needed."""
        f = PIIFilter(redact=True)
        ctx = ActionContext(
            action="test",
            payload={"contact": "user@example.com"},
        )
        result = await f.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.recovery is None


# ── AOWHandler recovery plans ────────────────────────────────


class TestAOWRecovery:
    async def test_pending_block_produces_correct_recovery(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=2)
        window = AOWWindow(action_id="deploy", earliest=future)
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.RETRY_AFTER_DELAY
        assert "opens_at" in result.recovery.context
        assert result.recovery.context["opens_at"] == future.isoformat()

    async def test_expired_block_produces_correct_recovery(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=3),
            latest=now - timedelta(hours=1),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.DELEGATE_TO_HUMAN
        assert RecoveryAction.RETRY_WITH_APPROVAL in result.recovery.alternatives

    async def test_blocked_by_deps_produces_correct_recovery(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            blocked_by=["tests_pass", "review_done"],
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.primary == RecoveryAction.RETRY_AFTER_DELAY
        assert "blocked_by" in result.recovery.context
        assert result.recovery.context["blocked_by"] == ["tests_pass", "review_done"]

    async def test_open_window_has_no_recovery(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            latest=now + timedelta(hours=1),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW
        assert result.recovery is None


# ── GovernanceError.recovery ─────────────────────────────────


class TestGovernanceErrorRecovery:
    def test_governance_error_exposes_recovery(self):
        recovery = RecoveryPlan(
            primary=RecoveryAction.RETRY_WITH_APPROVAL,
            alternatives=[RecoveryAction.DELEGATE_TO_HUMAN],
        )
        result = GovernanceResult.abort(
            handler_name="test",
            reason="blocked for testing",
            recovery=recovery,
        )
        error = GovernanceError(result)
        assert error.recovery is not None
        assert error.recovery.primary == RecoveryAction.RETRY_WITH_APPROVAL
        assert error.recovery.has(RecoveryAction.DELEGATE_TO_HUMAN)

    def test_governance_error_recovery_none_when_no_plan(self):
        result = GovernanceResult.abort(
            handler_name="test",
            reason="blocked without recovery",
        )
        error = GovernanceError(result)
        assert error.recovery is None

    async def test_governed_decorator_error_has_recovery(self):
        """End-to-end: @governed function raises GovernanceError with recovery."""
        from governed_agents.decorator import governed

        reset_pipeline()
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=2)
        async def restricted_action():
            return "should not reach"

        with pytest.raises(GovernanceError) as exc_info:
            await restricted_action()

        assert exc_info.value.recovery is not None
        assert exc_info.value.recovery.primary == RecoveryAction.RETRY_WITH_APPROVAL

        reset_pipeline()
