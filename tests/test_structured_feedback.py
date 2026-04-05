"""Tests for GAP 1: Structured Rejection Feedback.

Every handler that can return BLOCK must include suggestion and alternatives
in the GovernanceResult, enabling agents to self-repair.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from governed_agents import ActionContext, Verdict
from governed_agents.aow import AOWHandler, AOWWindow
from governed_agents.handlers import BudgetGatekeeper, PIIFilter, RateLimiter
from governed_agents.handlers.budget import ManualCostTracker
from governed_agents.vt import VTGovernanceHandler


# ── GovernanceResult dataclass ────────────────────────────


class TestGovernanceResultFeedback:
    def test_abort_has_default_empty_feedback(self):
        from governed_agents import GovernanceResult

        r = GovernanceResult.abort(handler_name="test", reason="blocked")
        assert r.suggestion == ""
        assert r.alternatives == []

    def test_abort_accepts_suggestion_and_alternatives(self):
        from governed_agents import GovernanceResult

        r = GovernanceResult.abort(
            handler_name="test",
            reason="blocked",
            suggestion="try X",
            alternatives=["option A", "option B"],
        )
        assert r.suggestion == "try X"
        assert r.alternatives == ["option A", "option B"]

    def test_continue_has_empty_feedback(self):
        from governed_agents import GovernanceResult

        r = GovernanceResult.continue_(handler_name="test", reason="ok")
        assert r.suggestion == ""
        assert r.alternatives == []


# ── VTGovernanceHandler ───────────────────────────────────


class TestVTFeedback:
    async def test_vt2_block_has_suggestion(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "ApprovalBackend" in result.suggestion
        assert "vt2_approved" in result.suggestion
        assert len(result.alternatives) == 2
        assert "Lower VT tier to VT1" in result.alternatives

    async def test_vt3_block_has_suggestion(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="deploy", agent_id="bot", vt_tier=3)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "advisory mode" in result.suggestion
        assert "Present as recommendation" in result.alternatives
        assert "Escalate to owner" in result.alternatives

    async def test_vt4_block_has_suggestion(self):
        handler = VTGovernanceHandler()
        ctx = ActionContext(action="delete_all", agent_id="bot", vt_tier=4)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "Owner-only" in result.suggestion
        assert result.alternatives == []


# ── BudgetGatekeeper ──────────────────────────────────────


class TestBudgetFeedback:
    async def test_budget_block_has_suggestion(self):
        tracker = ManualCostTracker()
        tracker.add_cost(10.0)
        bg = BudgetGatekeeper(budget_limit_usd=5.0, cost_provider=tracker)
        ctx = ActionContext(action="test")
        result = await bg.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "cheaper model" in result.suggestion
        assert "Use a lighter model" in result.alternatives
        assert "Batch with other requests" in result.alternatives
        assert "Request budget increase" in result.alternatives


# ── RateLimiter ───────────────────────────────────────────


class TestRateLimiterFeedback:
    async def test_rate_limit_block_has_suggestion(self):
        rl = RateLimiter(max_per_window=1, window_seconds=60)
        ctx = ActionContext(action="test", agent_id="bot")
        await rl.evaluate(ctx)  # First call OK
        result = await rl.evaluate(ctx)  # Second call blocked
        assert result.action == Verdict.BLOCK
        assert "Wait" in result.suggestion
        assert "Reduce action frequency" in result.alternatives
        assert "Batch actions" in result.alternatives

    async def test_rate_limit_suggestion_includes_wait_time(self):
        rl = RateLimiter(max_per_window=1, window_seconds=30)
        ctx = ActionContext(action="test", agent_id="bot")
        await rl.evaluate(ctx)
        result = await rl.evaluate(ctx)
        # Should include a numeric wait time
        assert "Wait" in result.suggestion
        assert "s" in result.suggestion


# ── PIIFilter ─────────────────────────────────────────────


class TestPIIFilterFeedback:
    async def test_pii_block_has_suggestion_and_field_alternatives(self):
        f = PIIFilter(redact=False)
        ctx = ActionContext(
            action="test",
            payload={"contact": "user@example.com", "data": "safe text"},
        )
        result = await f.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "Remove PII" in result.suggestion
        # Alternatives should list the affected fields
        assert any("contact" in alt for alt in result.alternatives)

    async def test_pii_redact_mode_no_block_feedback(self):
        """When redact=True, PII is modified not blocked, so no suggestion needed."""
        f = PIIFilter(redact=True)
        ctx = ActionContext(
            action="test",
            payload={"contact": "user@example.com"},
        )
        result = await f.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.suggestion == ""


# ── AOWHandler ────────────────────────────────────────────


class TestAOWFeedback:
    async def test_pending_block_has_suggestion(self):
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
        assert "opens at" in result.suggestion
        assert "Wait for window" in result.alternatives
        assert "Request early access" in result.alternatives

    async def test_expired_block_has_suggestion(self):
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
        assert "closed at" in result.suggestion
        assert "Request extension" in result.alternatives
        assert "Create new AOW" in result.alternatives

    async def test_blocked_by_deps_has_suggestion(self):
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
        assert "tests_pass" in result.suggestion
        assert "review_done" in result.suggestion
        assert "Complete blockers first" in result.alternatives
