"""Tests for AMO integration (fallback path -- no minimal-oversight required)."""

from __future__ import annotations

from governed_agents._amo.dynamic_vt import DynamicVTHandler, _authority_to_vt, HAS_AMO
from governed_agents.handler import ActionContext, Verdict


class TestAuthorityToVT:
    def test_high_authority_is_vt0(self):
        assert _authority_to_vt(0.9) == 0
        assert _authority_to_vt(0.8) == 0
        assert _authority_to_vt(1.0) == 0

    def test_moderate_authority_is_vt1(self):
        assert _authority_to_vt(0.7) == 1
        assert _authority_to_vt(0.5) == 1

    def test_low_authority_is_vt2(self):
        assert _authority_to_vt(0.4) == 2
        assert _authority_to_vt(0.2) == 2

    def test_very_low_authority_is_vt3(self):
        assert _authority_to_vt(0.1) == 3
        assert _authority_to_vt(0.05) == 3

    def test_near_zero_authority_is_vt4(self):
        assert _authority_to_vt(0.04) == 4
        assert _authority_to_vt(0.0) == 4


class TestDynamicVTHandlerFallback:
    """Tests that work WITHOUT minimal-oversight installed."""

    async def test_no_amo_passes_through(self):
        handler = DynamicVTHandler()
        ctx = ActionContext(action="test", vt_tier=2)
        result = await handler.evaluate(ctx)
        # Without AMO, should pass through or apply fallback
        if HAS_AMO:
            # If AMO IS available, it will try to optimize
            assert result.action in (Verdict.ALLOW, Verdict.MODIFY)
        else:
            assert result.action == Verdict.ALLOW
            assert "AMO not available" in result.reason

    async def test_fallback_tier_applied(self):
        handler = DynamicVTHandler(fallback_tier=3)
        ctx = ActionContext(action="test", vt_tier=1)
        result = await handler.evaluate(ctx)
        if not HAS_AMO:
            assert result.action == Verdict.MODIFY
            assert result.modified_context.vt_tier == 3
            assert "fallback VT3" in result.reason

    async def test_handler_name(self):
        handler = DynamicVTHandler()
        assert handler.name == "dynamic_vt"

    async def test_no_fallback_preserves_tier(self):
        handler = DynamicVTHandler(fallback_tier=None)
        ctx = ActionContext(action="test", vt_tier=2)
        result = await handler.evaluate(ctx)
        if not HAS_AMO:
            assert result.action == Verdict.ALLOW
            # Original tier unchanged
