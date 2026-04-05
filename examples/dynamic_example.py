"""Dynamic features -- AOW windows and Decision Debt.

Demonstrates the stateful governance features:
- AOW (Action Opportunity Windows): time-bounded decision scheduling
- Decision Debt: tracking deferred decisions as accumulating risk

Standalone demo -- no LLM needed.

Run: python examples/dynamic_example.py
"""

from datetime import datetime, timedelta, timezone

from governed_agents.aow import AOWWindow
from governed_agents.decision_debt import DecisionDebt, DecisionDebtLedger


def demo_aow():
    """Show AOW window lifecycle: OPEN -> EXPIRING -> EXPIRED."""
    print("=== AOW: Action Opportunity Windows ===\n")

    now = datetime.now(timezone.utc)
    window = AOWWindow(
        action_id="submit_tax_return",
        earliest=now - timedelta(hours=2),
        optimal=now,
        latest=now + timedelta(hours=1),
        expiry_warning_minutes=45,
    )

    # Evaluate at different points in time
    state = window.evaluate(now)
    print(f"  Now (within window):  {state.value}")

    state = window.evaluate(now + timedelta(minutes=20))
    print(f"  +20min (expiring):    {state.value}")

    state = window.evaluate(now + timedelta(hours=2))
    print(f"  +2h (expired):        {state.value}")

    # Terminal state is latched
    state = window.evaluate(now)
    print(f"  Re-check (latched):   {state.value}")
    print()


def demo_decision_debt():
    """Show Decision Debt lifecycle: defer -> escalate -> risk scoring."""
    print("=== Decision Debt Ledger ===\n")

    ledger = DecisionDebtLedger()
    now = datetime.now(timezone.utc)

    debt = DecisionDebt(
        debt_id="DD-001",
        action="approve_vendor_contract",
        agent_id="finance-agent",
        vt_tier=2,
        summary="$50k vendor contract needs owner sign-off",
        deadline=now + timedelta(days=7),
        max_deferrals=3,
    )
    ledger.add(debt)

    # Defer twice (still under threshold)
    for i in range(1, 3):
        state = ledger.defer("DD-001", reason=f"Busy, deferral #{i}")
        risk = debt.risk_score(now + timedelta(days=i))
        print(f"  Deferral {i}: state={state.value}, risk={risk:.2f}")

    print(f"\n  Needs escalation?      {len(ledger.escalation_candidates)} candidate(s)")
    print(f"  Total ledger risk:     {ledger.total_risk(now + timedelta(days=2)):.2f}")

    # Third deferral hits max_deferrals -> auto-escalates
    state = ledger.defer("DD-001", reason="Still busy, deferral #3")
    print(f"\n  Deferral 3: state={state.value} (auto-escalated at threshold)")
    print(f"  Risk score:            {debt.risk_score(now + timedelta(days=3)):.2f}")

    # Resolve the escalated debt
    debt.resolve("Contract approved after legal review")
    print(f"\n  After resolution:      state={debt.state.value}")
    print(f"  Pending debts:         {len(ledger.pending)}")
    print()


if __name__ == "__main__":
    demo_aow()
    demo_decision_debt()
