"""Tests for VT governance tier system."""

from __future__ import annotations

import pytest

from governed_agents import CallbackContext, ResultAction
from governed_agents.vt import VTGovernanceHandler, VTPolicy, VTTier


# ── VTTier enum ──────────────────────────────────


class TestVTTier:
    def test_values(self):
        assert VTTier.AUTO == 0
        assert VTTier.LOG == 1
        assert VTTier.APPROVE == 2
        assert VTTier.ADVISE == 3
        assert VTTier.BLOCK == 4

    def test_labels(self):
        assert VTTier.AUTO.label == "Autonomous"
        assert VTTier.LOG.label == "Log & Proceed"
        assert VTTier.APPROVE.label == "Require Approval"
        assert VTTier.ADVISE.label == "Advise Only"
        assert VTTier.BLOCK.label == "Owner Only"

    def test_policies(self):
        assert VTTier.AUTO.policy == "auto"
        assert VTTier.LOG.policy == "log"
        assert VTTier.APPROVE.policy == "approve"
        assert VTTier.ADVISE.policy == "advise"
        assert VTTier.BLOCK.policy == "block"

    def test_int_comparison(self):
        assert VTTier.AUTO < VTTier.LOG < VTTier.APPROVE < VTTier.ADVISE < VTTier.BLOCK


# ── VTPolicy ─────────────────────────────────────


class TestVTPolicy:
    def test_for_tier_0(self):
        p = VTPolicy.for_tier(0)
        assert p.action == "auto"
        assert p.allows_execution is True
        assert p.requires_approval is False

    def test_for_tier_2(self):
        p = VTPolicy.for_tier(2)
        assert p.action == "approve"
        assert p.requires_approval is True

    def test_for_tier_4(self):
        p = VTPolicy.for_tier(4)
        assert p.action == "block"
        assert p.allows_execution is False
        assert p.requires_approval is True

    def test_unknown_tier_defaults_to_block(self):
        p = VTPolicy.for_tier(99)
        assert p.action == "block"
        assert p.allows_execution is False


# ── VTGovernanceHandler ──────────────────────────


@pytest.fixture
def handler() -> VTGovernanceHandler:
    return VTGovernanceHandler()


class TestVTGovernanceHandler:
    async def test_vt0_auto_approves(self, handler):
        ctx = CallbackContext(action="read_data", vt_tier=0)
        result = await handler.check(ctx)
        assert result.action == ResultAction.CONTINUE
        assert "auto-approved" in result.reason

    async def test_vt1_logs_and_proceeds(self, handler):
        ctx = CallbackContext(action="log_action", agent_id="bot", vt_tier=1)
        result = await handler.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.metadata["governance_review_required"] is True

    async def test_vt2_blocks_without_approval(self, handler):
        ctx = CallbackContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "requires owner approval" in result.reason

    async def test_vt2_passes_with_approval(self, handler):
        ctx = CallbackContext(
            action="send_email", agent_id="bot", vt_tier=2,
            metadata={"vt2_approved": True},
        )
        result = await handler.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.metadata["governance_approval_verified"] is True

    async def test_vt3_advise_only(self, handler):
        ctx = CallbackContext(action="deploy", agent_id="bot", vt_tier=3)
        result = await handler.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "advise" in result.reason.lower()

    async def test_vt4_blocks(self, handler):
        ctx = CallbackContext(action="delete_all", agent_id="bot", vt_tier=4)
        result = await handler.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "owner-only" in result.reason.lower()

    async def test_unknown_tier_blocks(self, handler):
        ctx = CallbackContext(action="unknown", vt_tier=99)
        result = await handler.check(ctx)
        assert result.action == ResultAction.ABORT
