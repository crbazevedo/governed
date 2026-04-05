"""Tests for BlastRadiusPolicy and BlastRadiusHandler."""

from __future__ import annotations

from governed_agents.blast_radius import BlastRadiusHandler, BlastRadiusPolicy
from governed_agents.handler import ActionContext, Verdict
from governed_agents.recovery import RecoveryAction


class TestBlastRadiusBasic:
    async def test_no_constraints_allows(self):
        handler = BlastRadiusHandler(BlastRadiusPolicy())
        ctx = ActionContext(action="read", agent_id="bot")
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_handler_name(self):
        handler = BlastRadiusHandler(BlastRadiusPolicy())
        assert handler.name == "blast_radius"


class TestCostConstraints:
    async def test_per_action_cost_blocks(self):
        policy = BlastRadiusPolicy(max_cost_per_action=1.0)
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="expensive",
            agent_id="bot",
            metadata={"estimated_cost_usd": 2.0},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.has(RecoveryAction.USE_CHEAPER_RESOURCE)

    async def test_per_action_cost_allows(self):
        policy = BlastRadiusPolicy(max_cost_per_action=5.0)
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="cheap",
            agent_id="bot",
            metadata={"estimated_cost_usd": 1.0},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_hourly_cost_accumulates(self):
        policy = BlastRadiusPolicy(max_cost_per_hour=2.5)
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="work",
            agent_id="bot",
            metadata={"estimated_cost_usd": 1.0},
        )
        # First: accumulated=0 + estimated=1.0 = 1.0 <= 2.5 → allow
        r1 = await handler.evaluate(ctx)
        assert r1.action == Verdict.ALLOW
        handler.record_cost(1.0)

        # Second: accumulated=1.0 + estimated=1.0 = 2.0 <= 2.5 → allow
        r2 = await handler.evaluate(ctx)
        assert r2.action == Verdict.ALLOW
        handler.record_cost(1.0)

        # Third: accumulated=2.0 + estimated=1.0 = 3.0 > 2.5 → block
        r3 = await handler.evaluate(ctx)
        assert r3.action == Verdict.BLOCK
        assert "Hourly cost" in r3.reason


class TestFrequencyConstraints:
    async def test_hourly_frequency_blocks(self):
        policy = BlastRadiusPolicy(max_actions_per_hour=2)
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="spam", agent_id="bot")
        await handler.evaluate(ctx)  # 1
        await handler.evaluate(ctx)  # 2
        result = await handler.evaluate(ctx)  # 3
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.has(RecoveryAction.BATCH_WITH_OTHERS)

    async def test_daily_frequency_blocks(self):
        policy = BlastRadiusPolicy(max_actions_per_day=3)
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="daily", agent_id="bot")
        for _ in range(3):
            await handler.evaluate(ctx)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK


class TestIrreversibility:
    async def test_irreversible_action_blocked(self):
        policy = BlastRadiusPolicy(
            max_irreversible_per_day=0,
            irreversible_actions=frozenset({"delete_database"}),
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="delete_database", agent_id="bot")
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "Irreversible" in result.reason

    async def test_reversible_action_allowed(self):
        policy = BlastRadiusPolicy(
            max_irreversible_per_day=0,
            irreversible_actions=frozenset({"delete_database"}),
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="read_data", agent_id="bot")
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_irreversible_with_budget(self):
        policy = BlastRadiusPolicy(
            max_irreversible_per_day=1,
            irreversible_actions=frozenset({"deploy"}),
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="deploy", agent_id="bot")
        r1 = await handler.evaluate(ctx)
        assert r1.action == Verdict.ALLOW  # First deploy OK
        r2 = await handler.evaluate(ctx)
        assert r2.action == Verdict.BLOCK  # Second deploy blocked


class TestScopeConstraints:
    async def test_blocked_scope(self):
        policy = BlastRadiusPolicy(
            blocked_scopes=frozenset({"production"}),
            scope_ceiling="staging",
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="deploy",
            agent_id="bot",
            metadata={"scope": "production"},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert result.recovery is not None
        assert result.recovery.has(RecoveryAction.RETRY_LOWER_SCOPE)
        assert result.recovery.context["max_scope"] == "staging"

    async def test_allowed_scope(self):
        policy = BlastRadiusPolicy(
            blocked_scopes=frozenset({"production"}),
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="deploy",
            agent_id="bot",
            metadata={"scope": "staging"},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW


class TestHighRiskElevation:
    async def test_high_risk_action_elevates_vt(self):
        policy = BlastRadiusPolicy(
            high_risk_actions=frozenset({"wire_transfer"}),
            high_risk_vt=3,
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="wire_transfer", agent_id="bot", vt_tier=1)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context.vt_tier == 3

    async def test_already_elevated_passes(self):
        policy = BlastRadiusPolicy(
            high_risk_actions=frozenset({"wire_transfer"}),
            high_risk_vt=2,
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(action="wire_transfer", agent_id="bot", vt_tier=3)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW


class TestMultipleViolations:
    async def test_multiple_constraints_reports_all(self):
        policy = BlastRadiusPolicy(
            max_cost_per_action=0.5,
            max_actions_per_hour=1,
        )
        handler = BlastRadiusHandler(policy)
        ctx = ActionContext(
            action="expensive_spam",
            agent_id="bot",
            metadata={"estimated_cost_usd": 1.0},
        )
        # First call: cost violation only (action count OK at 0)
        r1 = await handler.evaluate(ctx)
        assert r1.action == Verdict.BLOCK

        # Force an allowed action to fill the counter
        cheap_ctx = ActionContext(action="ok", agent_id="bot")
        await handler.evaluate(cheap_ctx)

        # Second call with expensive action: both cost + frequency violated
        r2 = await handler.evaluate(ctx)
        assert r2.action == Verdict.BLOCK
        assert r2.recovery is not None
        assert len(r2.recovery.context) > 0 or len(r2.reason) > 20
