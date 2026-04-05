"""Decision Debt -- tracking deferred decisions as accumulating risk.

# Layer: Dynamic (stateful runtime)

When a human defers a VT2+ decision, it enters the Decision Debt ledger.
Deferred decisions accumulate risk: after N deferrals or approaching deadline,
they auto-escalate. This prevents decision paralysis in governed systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DebtState(str, Enum):
    """Lifecycle state of a deferred decision."""

    PENDING = "pending"  # Awaiting first decision
    DEFERRED = "deferred"  # Human chose to defer
    REMINDED = "reminded"  # System sent a reminder
    REASSESSED = "reassessed"  # Decision was re-evaluated
    RESOLVED = "resolved"  # Decision was made
    ABORTED = "aborted"  # Action no longer relevant
    ESCALATED = "escalated"  # Auto-escalated due to risk


@dataclass
class DecisionDebt:
    """A deferred decision tracked as accumulating risk.

    Each deferral increases the deferral_count. When thresholds
    are crossed, the decision auto-escalates.
    """

    debt_id: str
    action: str
    agent_id: str
    vt_tier: int
    summary: str
    state: DebtState = DebtState.PENDING
    deferral_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: datetime | None = None
    last_reminded: datetime | None = None
    resolved_at: datetime | None = None
    resolution: str = ""
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Escalation thresholds
    max_deferrals: int = 3
    escalation_threshold: float = 0.5
    """Fraction of deadline elapsed that triggers escalation.
    0.5 = escalate at the halfway point. 0.75 = escalate at 75%."""

    def defer(self, reason: str = "") -> DebtState:
        """Record a deferral. Returns new state (may escalate)."""
        self.deferral_count += 1
        self.metadata.setdefault("deferral_reasons", []).append(reason)

        if self.deferral_count >= self.max_deferrals:
            self.state = DebtState.ESCALATED
            return self.state

        self.state = DebtState.DEFERRED
        return self.state

    def remind(self) -> None:
        """Record that a reminder was sent."""
        self.state = DebtState.REMINDED
        self.last_reminded = datetime.now(timezone.utc)

    def resolve(self, resolution: str) -> None:
        """Mark as resolved with the decision made."""
        self.state = DebtState.RESOLVED
        self.resolution = resolution
        self.resolved_at = datetime.now(timezone.utc)

    def abort(self, reason: str = "") -> None:
        """Mark as aborted (no longer relevant)."""
        self.state = DebtState.ABORTED
        self.resolution = reason
        self.resolved_at = datetime.now(timezone.utc)

    def should_escalate(self, now: datetime | None = None) -> bool:
        """Check if this debt should be escalated based on thresholds."""
        if self.state in (DebtState.RESOLVED, DebtState.ABORTED, DebtState.ESCALATED):
            return False

        # Deferral count threshold
        if self.deferral_count >= self.max_deferrals:
            return True

        # Deadline proximity threshold
        if self.deadline:
            now = now or datetime.now(timezone.utc)
            total_duration = (self.deadline - self.created_at).total_seconds()
            elapsed = (now - self.created_at).total_seconds()
            if total_duration > 0 and elapsed / total_duration >= self.escalation_threshold:
                return True

        return False

    def risk_score(self, now: datetime | None = None) -> float:
        """Compute a risk score (0.0-1.0) based on deferrals and deadline proximity.

        Args:
            now: Current time. Defaults to UTC now. Pass explicitly for deterministic testing.
        """
        now = now or datetime.now(timezone.utc)
        score = 0.0

        # Deferral risk (0-0.5)
        score += min(self.deferral_count / max(self.max_deferrals, 1), 1.0) * 0.5

        # Deadline risk (0-0.5)
        if self.deadline:
            total = (self.deadline - self.created_at).total_seconds()
            elapsed = (now - self.created_at).total_seconds()
            if total > 0:
                score += min(elapsed / total, 1.0) * 0.5

        return min(score, 1.0)


class DecisionDebtLedger:
    """In-memory ledger tracking all deferred decisions.

    The ledger provides aggregate risk metrics and identifies
    decisions requiring escalation.

    Note: This ledger is NOT thread-safe or async-safe. If multiple
    pipeline executions may access it concurrently, the caller must
    provide external synchronization (e.g., asyncio.Lock). For
    production use, implement persistence via a backend adapter.
    """

    def __init__(self) -> None:
        self._debts: dict[str, DecisionDebt] = {}

    def add(self, debt: DecisionDebt) -> None:
        """Add a decision to the ledger."""
        self._debts[debt.debt_id] = debt

    def get(self, debt_id: str) -> DecisionDebt | None:
        """Get a decision by ID."""
        return self._debts.get(debt_id)

    def defer(self, debt_id: str, reason: str = "") -> DebtState | None:
        """Record a deferral for a decision."""
        debt = self._debts.get(debt_id)
        if debt:
            return debt.defer(reason)
        return None

    def resolve(self, debt_id: str, resolution: str) -> None:
        """Resolve a decision."""
        debt = self._debts.get(debt_id)
        if debt:
            debt.resolve(resolution)

    @property
    def pending(self) -> list[DecisionDebt]:
        """All unresolved debts."""
        return [
            d
            for d in self._debts.values()
            if d.state not in (DebtState.RESOLVED, DebtState.ABORTED)
        ]

    @property
    def escalation_candidates(self) -> list[DecisionDebt]:
        """Debts that should be escalated."""
        return [d for d in self.pending if d.should_escalate()]

    def total_risk(self, now: datetime | None = None) -> float:
        """Aggregate risk score across all pending debts."""
        pending = self.pending
        if not pending:
            return 0.0
        return sum(d.risk_score(now) for d in pending) / len(pending)

    @property
    def count(self) -> int:
        return len(self._debts)
