"""Tests for TrustLedger protocol — earned autonomy through observed outcomes."""

from __future__ import annotations


from governed_agents import ActionContext, Verdict
from governed_agents.trust import (
    Outcome,
    TrustEvolutionHandler,
    TrustLedger,
    TrustSignal,
    VTTransition,
)


# ── Helpers ─────────────────────────────────────


def _make_outcome(
    agent_id: str = "bot",
    action: str = "send_email",
    succeeded: bool | None = True,
    human_decision: str = "",
    verdict: str = "allow",
) -> Outcome:
    return Outcome(
        action=action,
        agent_id=agent_id,
        verdict=verdict,
        human_decision=human_decision,
        succeeded=succeeded,
    )


def _fill_successes(
    ledger: TrustLedger, n: int, agent_id: str = "bot", action: str = "send_email"
) -> None:
    """Record n successful outcomes."""
    for _ in range(n):
        ledger.record(_make_outcome(agent_id=agent_id, action=action, succeeded=True))


def _fill_failures(
    ledger: TrustLedger, n: int, agent_id: str = "bot", action: str = "send_email"
) -> None:
    """Record n failed outcomes."""
    for _ in range(n):
        ledger.record(
            _make_outcome(
                agent_id=agent_id,
                action=action,
                succeeded=False,
                human_decision="rejected",
                verdict="block",
            )
        )


# ── 1. TrustLedger basics ──────────────────────


class TestTrustLedgerBasics:
    def test_signal_no_data_returns_defaults(self):
        ledger = TrustLedger()
        sig = ledger.signal("bot", "send_email")
        assert sig.sigma_raw == 0.5
        assert sig.sigma_corr == 0.5
        assert sig.masking_index == 1.0
        assert sig.observation_count == 0
        assert sig.last_observed == 0.0
        assert sig.recommended_vt is None

    def test_record_and_count(self):
        ledger = TrustLedger()
        ledger.record(_make_outcome())
        ledger.record(_make_outcome())
        sig = ledger.signal("bot", "send_email")
        assert sig.observation_count == 2

    def test_signal_with_all_approvals_approaches_one(self):
        ledger = TrustLedger(min_observations=5)
        for _ in range(30):
            ledger.record(_make_outcome(succeeded=True, human_decision="approved"))
        sig = ledger.signal("bot", "send_email")
        assert sig.sigma_raw >= 0.95
        assert sig.sigma_corr >= 0.95

    def test_signal_with_all_rejections_approaches_zero(self):
        ledger = TrustLedger(min_observations=5)
        for _ in range(30):
            ledger.record(
                _make_outcome(succeeded=False, human_decision="rejected", verdict="block")
            )
        sig = ledger.signal("bot", "send_email")
        assert sig.sigma_raw <= 0.05
        assert sig.sigma_corr <= 0.05

    def test_different_agent_action_pairs_independent(self):
        ledger = TrustLedger()
        _fill_successes(ledger, 10, agent_id="alpha", action="read")
        _fill_failures(ledger, 10, agent_id="beta", action="write")
        sig_alpha = ledger.signal("alpha", "read")
        sig_beta = ledger.signal("beta", "write")
        assert sig_alpha.sigma_raw > 0.9
        assert sig_beta.sigma_raw < 0.1


# ── 2. Decay ───────────────────────────────────


class TestDecay:
    def test_recent_observations_weight_more(self):
        ledger = TrustLedger(decay_rate=0.05)
        # First 20: all failures
        _fill_failures(ledger, 20)
        # Then 20: all successes
        _fill_successes(ledger, 20)
        sig = ledger.signal("bot", "send_email")
        # With decay, recent successes should pull sigma_raw well above 0.5
        assert sig.sigma_raw > 0.6

    def test_old_observations_decay_with_high_rate(self):
        ledger = TrustLedger(decay_rate=0.10)
        # 20 successes followed by 20 failures
        _fill_successes(ledger, 20)
        _fill_failures(ledger, 20)
        sig = ledger.signal("bot", "send_email")
        # Recent failures dominate with high decay
        assert sig.sigma_raw < 0.4

    def test_zero_decay_weights_all_equally(self):
        ledger = TrustLedger(decay_rate=0.0)
        # 10 successes then 10 failures
        _fill_successes(ledger, 10)
        _fill_failures(ledger, 10)
        sig = ledger.signal("bot", "send_email")
        # Equal weighting means ~0.5
        assert 0.45 <= sig.sigma_raw <= 0.55


# ── 3. VT recommendation ──────────────────────


class TestVTRecommendation:
    def test_high_sigma_promotes(self):
        ledger = TrustLedger(min_observations=10, promote_threshold=0.85)
        _fill_successes(ledger, 30)
        sig = ledger.signal("bot", "send_email")
        # sigma_raw ~1.0 -> sigma_to_vt returns 0, promote lowers by 1 -> stays 0
        # but recommended_vt should be low (0)
        assert sig.recommended_vt is not None
        assert sig.recommended_vt <= 1

    def test_low_sigma_demotes(self):
        ledger = TrustLedger(min_observations=10, demote_threshold=0.50)
        _fill_failures(ledger, 30)
        sig = ledger.signal("bot", "send_email")
        assert sig.recommended_vt is not None
        assert sig.recommended_vt >= 3

    def test_moderate_sigma_holds_tier(self):
        ledger = TrustLedger(min_observations=10, promote_threshold=0.85, demote_threshold=0.50)
        # Mix of successes and failures to get sigma ~0.65
        _fill_successes(ledger, 13)
        _fill_failures(ledger, 7)
        sig = ledger.signal("bot", "send_email")
        # Between thresholds -> sigma_to_vt without promotion/demotion
        assert sig.recommended_vt is not None

    def test_recommend_returns_transition_for_promote(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85)
        _fill_successes(ledger, 20)
        rec = ledger.recommend("bot", "send_email", current_vt=2)
        assert rec is not None
        assert rec.direction == "promote"
        assert rec.recommended_vt < 2

    def test_recommend_returns_transition_for_demote(self):
        ledger = TrustLedger(min_observations=5, demote_threshold=0.50)
        _fill_failures(ledger, 20)
        rec = ledger.recommend("bot", "send_email", current_vt=1)
        assert rec is not None
        assert rec.direction == "demote"
        assert rec.recommended_vt > 1

    def test_recommend_none_when_no_change_needed(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85, demote_threshold=0.50)
        # All successes -> sigma ~1.0 -> recommended VT 0, current VT is 0
        _fill_successes(ledger, 20)
        rec = ledger.recommend("bot", "send_email", current_vt=0)
        # Already at VT0, can't promote further
        assert rec is None


# ── 4. Monotonic constraint ───────────────────


class TestMonotonicConstraint:
    def test_max_one_level_promotion(self):
        ledger = TrustLedger(
            min_observations=5, promote_threshold=0.85, max_vt_change_per_period=1
        )
        _fill_successes(ledger, 30)
        # sigma ~1.0 would recommend VT0, but from VT3 can only go to VT2
        rec = ledger.recommend("bot", "send_email", current_vt=3)
        assert rec is not None
        assert rec.recommended_vt == 2  # Only one level change

    def test_max_one_level_demotion(self):
        ledger = TrustLedger(min_observations=5, demote_threshold=0.50, max_vt_change_per_period=1)
        _fill_failures(ledger, 30)
        # sigma ~0.0 would recommend VT4, but from VT1 can only go to VT2
        rec = ledger.recommend("bot", "send_email", current_vt=1)
        assert rec is not None
        assert rec.recommended_vt == 2  # Only one level change

    def test_custom_max_change(self):
        ledger = TrustLedger(
            min_observations=5, promote_threshold=0.85, max_vt_change_per_period=2
        )
        _fill_successes(ledger, 30)
        rec = ledger.recommend("bot", "send_email", current_vt=4)
        assert rec is not None
        assert rec.recommended_vt >= 2  # At most 2 levels from 4


# ── 5. Masking detection ─────────────────────


class TestMaskingDetection:
    def test_masking_index_high_when_corrected_exceeds_raw(self):
        ledger = TrustLedger()
        # Outcomes where human corrects the agent: raw is low, corrected is high
        for _ in range(15):
            ledger.record(
                Outcome(
                    action="draft",
                    agent_id="bot",
                    verdict="modify",
                    human_decision="edited",  # Raw: 0 (agent wrong)
                    succeeded=True,  # Corrected: 1 (final output OK)
                )
            )
        sig = ledger.signal("bot", "draft")
        # sigma_raw should be low (agent keeps failing), sigma_corr should be high (human fixes it)
        assert sig.sigma_raw < 0.1
        assert sig.sigma_corr > 0.9
        assert sig.masking_index > 1.3

    def test_masking_alerts_returns_flagged_signals(self):
        ledger = TrustLedger()
        for _ in range(15):
            ledger.record(
                Outcome(
                    action="draft",
                    agent_id="bot",
                    verdict="modify",
                    human_decision="edited",
                    succeeded=True,
                )
            )
        alerts = ledger.masking_alerts
        assert len(alerts) == 1
        assert alerts[0].action == "draft"
        assert alerts[0].masking_index > 1.3

    def test_masking_alerts_empty_when_no_masking(self):
        ledger = TrustLedger()
        _fill_successes(ledger, 15)
        alerts = ledger.masking_alerts
        assert len(alerts) == 0

    def test_masking_alerts_ignores_low_observation_count(self):
        ledger = TrustLedger()
        # Only 5 observations (below threshold of 10)
        for _ in range(5):
            ledger.record(
                Outcome(
                    action="draft",
                    agent_id="bot",
                    verdict="modify",
                    human_decision="edited",
                    succeeded=True,
                )
            )
        alerts = ledger.masking_alerts
        assert len(alerts) == 0


# ── 6. TrustEvolutionHandler ─────────────────


class TestTrustEvolutionHandler:
    async def test_adjusts_vt_tier_downward_on_promotion(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85)
        _fill_successes(ledger, 20)
        handler = TrustEvolutionHandler(ledger)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.vt_tier < 2
        assert result.modified_context.metadata["trust_transition"] == "promote"
        assert result.modified_context.metadata["trust_original_vt"] == 2

    async def test_adjusts_vt_tier_upward_on_demotion(self):
        ledger = TrustLedger(min_observations=5, demote_threshold=0.50)
        _fill_failures(ledger, 20)
        handler = TrustEvolutionHandler(ledger)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=1)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.vt_tier > 1
        assert result.modified_context.metadata["trust_transition"] == "demote"

    async def test_insufficient_evidence_allows_through(self):
        ledger = TrustLedger(min_observations=20)
        _fill_successes(ledger, 5)  # Way below min_observations
        handler = TrustEvolutionHandler(ledger)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW
        assert "Insufficient evidence" in result.reason

    async def test_no_change_when_trust_confirms_tier(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85, demote_threshold=0.50)
        # All successes -> VT0 recommended, current is VT0 -> no change
        _fill_successes(ledger, 20)
        handler = TrustEvolutionHandler(ledger)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=0)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_metadata_includes_trust_signals(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85)
        _fill_successes(ledger, 20)
        handler = TrustEvolutionHandler(ledger)
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        meta = result.modified_context.metadata
        assert "trust_sigma_raw" in meta
        assert "trust_sigma_corr" in meta
        assert "trust_masking" in meta
        assert "trust_observations" in meta
        assert meta["trust_observations"] == 20


# ── 7. Floor constraint ──────────────────────


class TestFloorConstraint:
    async def test_floor_prevents_promotion_below_floor(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85)
        _fill_successes(ledger, 30)
        # Floor for send_email is VT2 — trust can't promote below that
        handler = TrustEvolutionHandler(ledger, vt_floors={"send_email": 2})
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await handler.evaluate(ctx)
        # Should ALLOW (no change) because floor prevents going below VT2
        assert result.action == Verdict.ALLOW

    async def test_floor_does_not_block_demotion_above_floor(self):
        ledger = TrustLedger(min_observations=5, demote_threshold=0.50)
        _fill_failures(ledger, 30)
        # Floor is VT1, current is VT1, demotion to VT2 is above floor -> allowed
        handler = TrustEvolutionHandler(ledger, vt_floors={"send_email": 1})
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=1)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context.vt_tier >= 1  # Floor respected

    async def test_no_floor_allows_full_promotion(self):
        ledger = TrustLedger(min_observations=5, promote_threshold=0.85)
        _fill_successes(ledger, 30)
        handler = TrustEvolutionHandler(ledger, vt_floors={})
        ctx = ActionContext(action="send_email", agent_id="bot", vt_tier=3)
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context.vt_tier < 3


# ── 8. Incident recording ───────────────────


class TestIncidentRecording:
    def test_incident_adds_failed_outcome(self):
        ledger = TrustLedger()
        ledger.record_incident("bot", "send_email")
        sig = ledger.signal("bot", "send_email")
        assert sig.observation_count == 1
        assert sig.sigma_raw == 0.0  # Failed + rejected = 0

    def test_incidents_demote_trust(self):
        ledger = TrustLedger(min_observations=5)
        # Build up trust
        _fill_successes(ledger, 10)
        sig_before = ledger.signal("bot", "send_email")
        # Add incidents
        for _ in range(10):
            ledger.record_incident("bot", "send_email")
        sig_after = ledger.signal("bot", "send_email")
        assert sig_after.sigma_raw < sig_before.sigma_raw

    def test_incident_has_correct_fields(self):
        ledger = TrustLedger()
        ledger.record_incident("bot", "deploy")
        outcome = ledger._outcomes[-1]
        assert outcome.agent_id == "bot"
        assert outcome.action == "deploy"
        assert outcome.verdict == "block"
        assert outcome.human_decision == "rejected"
        assert outcome.succeeded is False


# ── 9. Insufficient evidence ────────────────


class TestInsufficientEvidence:
    def test_no_recommendation_below_min_observations(self):
        ledger = TrustLedger(min_observations=20)
        _fill_successes(ledger, 19)
        rec = ledger.recommend("bot", "send_email", current_vt=2)
        assert rec is None

    def test_recommendation_at_exactly_min_observations(self):
        ledger = TrustLedger(min_observations=20, promote_threshold=0.85)
        _fill_successes(ledger, 20)
        sig = ledger.signal("bot", "send_email")
        assert sig.recommended_vt is not None

    def test_signal_has_no_recommended_vt_below_min(self):
        ledger = TrustLedger(min_observations=10)
        _fill_successes(ledger, 5)
        sig = ledger.signal("bot", "send_email")
        assert sig.recommended_vt is None


# ── 10. all_signals and masking_alerts ──────


class TestAllSignalsAndMaskingAlerts:
    def test_all_signals_returns_all_pairs(self):
        ledger = TrustLedger()
        ledger.record(_make_outcome(agent_id="a", action="x"))
        ledger.record(_make_outcome(agent_id="a", action="y"))
        ledger.record(_make_outcome(agent_id="b", action="x"))
        signals = ledger.all_signals
        pairs = {(s.agent_id, s.action) for s in signals}
        assert pairs == {("a", "x"), ("a", "y"), ("b", "x")}

    def test_all_signals_empty_ledger(self):
        ledger = TrustLedger()
        assert ledger.all_signals == []

    def test_all_signals_deduplicates(self):
        ledger = TrustLedger()
        _fill_successes(ledger, 5, agent_id="bot", action="read")
        signals = ledger.all_signals
        assert len(signals) == 1
        assert signals[0].observation_count == 5

    def test_masking_alerts_across_multiple_agents(self):
        ledger = TrustLedger()
        # Agent A: masking (edited but succeeds)
        for _ in range(15):
            ledger.record(
                Outcome(action="write", agent_id="a", human_decision="edited", succeeded=True)
            )
        # Agent B: no masking (genuine successes)
        for _ in range(15):
            ledger.record(
                Outcome(action="write", agent_id="b", human_decision="approved", succeeded=True)
            )
        alerts = ledger.masking_alerts
        agent_ids = [a.agent_id for a in alerts]
        assert "a" in agent_ids
        assert "b" not in agent_ids


# ── Edge cases ──────────────────────────────


class TestEdgeCases:
    def test_sigma_to_vt_boundaries(self):
        assert TrustLedger._sigma_to_vt(1.0) == 0
        assert TrustLedger._sigma_to_vt(0.90) == 0
        assert TrustLedger._sigma_to_vt(0.89) == 1
        assert TrustLedger._sigma_to_vt(0.75) == 1
        assert TrustLedger._sigma_to_vt(0.74) == 2
        assert TrustLedger._sigma_to_vt(0.55) == 2
        assert TrustLedger._sigma_to_vt(0.54) == 3
        assert TrustLedger._sigma_to_vt(0.35) == 3
        assert TrustLedger._sigma_to_vt(0.34) == 4
        assert TrustLedger._sigma_to_vt(0.0) == 4

    def test_unknown_outcomes_scored_as_neutral(self):
        ledger = TrustLedger()
        # All unknown outcomes (no succeeded, no human_decision)
        for _ in range(20):
            ledger.record(Outcome(action="test", agent_id="bot"))
        sig = ledger.signal("bot", "test")
        # Raw should be ~0.5 (neutral), corrected should be ~0.0 (nothing confirmed)
        assert 0.45 <= sig.sigma_raw <= 0.55

    def test_confidence_scales_with_observations(self):
        ledger = TrustLedger(min_observations=10, promote_threshold=0.85)
        _fill_successes(ledger, 10)
        rec10 = ledger.recommend("bot", "send_email", current_vt=2)
        _fill_successes(ledger, 20)
        rec30 = ledger.recommend("bot", "send_email", current_vt=2)
        # More observations -> higher confidence (capped at 1.0)
        assert rec10 is not None
        assert rec30 is not None
        assert rec30.confidence >= rec10.confidence

    def test_outcome_dataclass_defaults(self):
        o = Outcome(action="test", agent_id="bot")
        assert o.verdict == ""
        assert o.human_decision == ""
        assert o.succeeded is None
        assert o.timestamp > 0

    def test_trust_signal_dataclass(self):
        sig = TrustSignal(
            agent_id="bot",
            action="test",
            sigma_raw=0.75,
            sigma_corr=0.80,
            masking_index=1.067,
            observation_count=50,
            last_observed=1000.0,
            recommended_vt=1,
        )
        assert sig.agent_id == "bot"
        assert sig.recommended_vt == 1

    def test_vt_transition_dataclass(self):
        t = VTTransition(
            agent_id="bot",
            action="test",
            current_vt=2,
            recommended_vt=1,
            direction="promote",
            confidence=0.75,
            evidence_count=30,
            reason="test reason",
        )
        assert t.direction == "promote"
        assert t.evidence_count == 30
