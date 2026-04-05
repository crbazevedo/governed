"""Tests for Decision Debt ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from governed_agents.decision_debt import (
    DebtState,
    DecisionDebt,
    DecisionDebtLedger,
)


# ── DecisionDebt lifecycle ────────────────────────────────────────────


class TestDecisionDebtLifecycle:
    def _make_debt(self, **kwargs) -> DecisionDebt:
        defaults = dict(
            debt_id="D001",
            action="deploy_prod",
            agent_id="eng",
            vt_tier=2,
            summary="Deploy to production",
        )
        defaults.update(kwargs)
        return DecisionDebt(**defaults)

    def test_initial_state_is_pending(self):
        debt = self._make_debt()
        assert debt.state == DebtState.PENDING
        assert debt.deferral_count == 0

    def test_defer_increments_count(self):
        debt = self._make_debt()
        state = debt.defer("Not ready yet")
        assert state == DebtState.DEFERRED
        assert debt.deferral_count == 1
        assert debt.metadata["deferral_reasons"] == ["Not ready yet"]

    def test_defer_multiple_times(self):
        debt = self._make_debt()
        debt.defer("Reason 1")
        debt.defer("Reason 2")
        assert debt.deferral_count == 2
        assert len(debt.metadata["deferral_reasons"]) == 2

    def test_defer_escalates_at_threshold(self):
        debt = self._make_debt(max_deferrals=3)
        debt.defer("1")
        debt.defer("2")
        state = debt.defer("3")
        assert state == DebtState.ESCALATED
        assert debt.deferral_count == 3

    def test_remind(self):
        debt = self._make_debt()
        debt.remind()
        assert debt.state == DebtState.REMINDED
        assert debt.last_reminded is not None

    def test_resolve(self):
        debt = self._make_debt()
        debt.defer("Later")
        debt.resolve("Approved by owner")
        assert debt.state == DebtState.RESOLVED
        assert debt.resolution == "Approved by owner"
        assert debt.resolved_at is not None

    def test_abort(self):
        debt = self._make_debt()
        debt.abort("No longer relevant")
        assert debt.state == DebtState.ABORTED
        assert debt.resolution == "No longer relevant"
        assert debt.resolved_at is not None


# ── Escalation logic ─────────────────────────────────────────────────


class TestDecisionDebtEscalation:
    def _make_debt(self, **kwargs) -> DecisionDebt:
        defaults = dict(
            debt_id="D001",
            action="deploy_prod",
            agent_id="eng",
            vt_tier=2,
            summary="Deploy to production",
        )
        defaults.update(kwargs)
        return DecisionDebt(**defaults)

    def test_should_not_escalate_when_fresh(self):
        debt = self._make_debt()
        assert not debt.should_escalate()

    def test_should_escalate_at_max_deferrals(self):
        debt = self._make_debt(max_deferrals=3)
        debt.defer("1")
        debt.defer("2")
        # 2 deferrals, but state is DEFERRED (not yet ESCALATED), and
        # we set max_deferrals=3 so the next defer would escalate.
        # However, should_escalate checks deferral_count >= max_deferrals.
        # With 2 < 3, should not escalate yet.
        assert not debt.should_escalate()
        debt.defer("3")  # This triggers escalation via defer()
        # Now state is ESCALATED, which is excluded from should_escalate
        assert debt.state == DebtState.ESCALATED
        # should_escalate returns False for already-escalated debts
        assert not debt.should_escalate()

    def test_should_not_escalate_when_resolved(self):
        debt = self._make_debt(max_deferrals=2)
        debt.defer("1")
        debt.defer("2")
        debt.resolve("Done")
        assert not debt.should_escalate()

    def test_should_not_escalate_when_aborted(self):
        debt = self._make_debt()
        debt.abort("Cancelled")
        assert not debt.should_escalate()

    def test_should_not_escalate_when_already_escalated(self):
        debt = self._make_debt(max_deferrals=1)
        debt.defer("1")  # This escalates
        assert debt.state == DebtState.ESCALATED
        assert not debt.should_escalate()

    def test_deadline_proximity_escalation(self):
        now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        debt = self._make_debt(
            created_at=now - timedelta(hours=6),
            deadline=now + timedelta(hours=6),
            deadline_escalation_factor=2.0,
        )
        # elapsed = 6h, total = 12h, ratio = 0.5, threshold = 1/2.0 = 0.5
        assert debt.should_escalate(now)

    def test_deadline_no_escalation_early(self):
        now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        debt = self._make_debt(
            created_at=now - timedelta(hours=1),
            deadline=now + timedelta(hours=11),
            deadline_escalation_factor=2.0,
        )
        # elapsed = 1h, total = 12h, ratio ~0.083, threshold = 0.5
        assert not debt.should_escalate(now)


# ── Risk scoring ─────────────────────────────────────────────────────


class TestDecisionDebtRiskScore:
    def _make_debt(self, **kwargs) -> DecisionDebt:
        defaults = dict(
            debt_id="D001",
            action="deploy_prod",
            agent_id="eng",
            vt_tier=2,
            summary="Deploy to production",
        )
        defaults.update(kwargs)
        return DecisionDebt(**defaults)

    def test_zero_risk_when_fresh(self):
        debt = self._make_debt()
        assert debt.risk_score == 0.0

    def test_deferral_risk_component(self):
        debt = self._make_debt(max_deferrals=10)
        debt.defer("1")
        debt.defer("2")
        # deferral_risk = (2/10) * 0.5 = 0.1, no deadline = 0 deadline risk
        assert debt.risk_score == pytest.approx(0.1)

    def test_max_deferrals_caps_at_half(self):
        debt = self._make_debt(max_deferrals=2)
        debt.defer("1")
        # 1 deferral, state = DEFERRED, deferral_risk = (1/2) * 0.5 = 0.25
        assert debt.risk_score == pytest.approx(0.25)
        debt.defer("2")  # Hits threshold, state -> ESCALATED
        # deferral_risk = min(2/2, 1.0) * 0.5 = 0.5
        assert debt.risk_score == pytest.approx(0.5)
        debt.defer("3")  # Over max
        # deferral_risk = min(3/2, 1.0) * 0.5 = 0.5 (capped)
        assert debt.risk_score == pytest.approx(0.5)

    def test_risk_score_bounded_at_one(self):
        now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        debt = self._make_debt(
            max_deferrals=1,
            created_at=now - timedelta(hours=24),
            deadline=now - timedelta(hours=1),  # Past deadline
        )
        debt.defer("1")
        debt.defer("2")
        # Both components maxed
        assert debt.risk_score <= 1.0


# ── DecisionDebtLedger ───────────────────────────────────────────────


class TestDecisionDebtLedger:
    def _make_debt(self, debt_id: str, **kwargs) -> DecisionDebt:
        defaults = dict(
            debt_id=debt_id,
            action="action",
            agent_id="eng",
            vt_tier=2,
            summary="Summary",
        )
        defaults.update(kwargs)
        return DecisionDebt(**defaults)

    def test_add_and_get(self):
        ledger = DecisionDebtLedger()
        debt = self._make_debt("D001")
        ledger.add(debt)
        assert ledger.get("D001") is debt
        assert ledger.count == 1

    def test_get_nonexistent_returns_none(self):
        ledger = DecisionDebtLedger()
        assert ledger.get("nonexistent") is None

    def test_defer_via_ledger(self):
        ledger = DecisionDebtLedger()
        debt = self._make_debt("D001")
        ledger.add(debt)
        state = ledger.defer("D001", "Not now")
        assert state == DebtState.DEFERRED
        assert debt.deferral_count == 1

    def test_defer_nonexistent_returns_none(self):
        ledger = DecisionDebtLedger()
        assert ledger.defer("nonexistent") is None

    def test_resolve_via_ledger(self):
        ledger = DecisionDebtLedger()
        debt = self._make_debt("D001")
        ledger.add(debt)
        ledger.resolve("D001", "Approved")
        assert debt.state == DebtState.RESOLVED

    def test_pending_excludes_resolved(self):
        ledger = DecisionDebtLedger()
        d1 = self._make_debt("D001")
        d2 = self._make_debt("D002")
        ledger.add(d1)
        ledger.add(d2)
        ledger.resolve("D001", "Done")
        assert len(ledger.pending) == 1
        assert ledger.pending[0].debt_id == "D002"

    def test_pending_excludes_aborted(self):
        ledger = DecisionDebtLedger()
        d1 = self._make_debt("D001")
        ledger.add(d1)
        d1.abort("Cancelled")
        assert len(ledger.pending) == 0

    def test_escalation_candidates(self):
        ledger = DecisionDebtLedger()
        d1 = self._make_debt("D001", max_deferrals=2)
        d2 = self._make_debt("D002", max_deferrals=5)
        ledger.add(d1)
        ledger.add(d2)
        ledger.defer("D001", "1")
        ledger.defer("D001", "2")  # Hits threshold
        assert len(ledger.escalation_candidates) == 0  # D001 is now ESCALATED state
        # D002 has no deferrals, so no escalation
        assert len(ledger.escalation_candidates) == 0

    def test_total_risk_empty(self):
        ledger = DecisionDebtLedger()
        assert ledger.total_risk == 0.0

    def test_total_risk_with_debts(self):
        ledger = DecisionDebtLedger()
        d1 = self._make_debt("D001", max_deferrals=10)
        d2 = self._make_debt("D002", max_deferrals=10)
        ledger.add(d1)
        ledger.add(d2)
        ledger.defer("D001", "1")
        ledger.defer("D001", "2")
        # d1 risk = (2/10)*0.5 = 0.1, d2 risk = 0.0, average = 0.05
        assert ledger.total_risk == pytest.approx(0.05)
