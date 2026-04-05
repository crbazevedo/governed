"""Action Opportunity Windows -- time-bounded decision scheduling.

# Layer: Dynamic (stateful runtime)

An AOW encodes WHEN a governed action can happen, not just WHETHER it can.
This separates authority (VT tiers) from timing (AOW windows).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.recovery import RecoveryAction, RecoveryPlan


class AOWState(str, Enum):
    """Lifecycle state of an Action Opportunity Window."""

    PENDING = "pending"  # Window not yet open
    OPEN = "open"  # Within the window, action can be taken
    OPTIMAL = "optimal"  # Within the preferred sub-window
    EXPIRING = "expiring"  # Window closing soon (configurable threshold)
    EXPIRED = "expired"  # Window closed, action no longer possible
    BLOCKED = "blocked"  # Externally blocked (dependency not met)
    COMPLETED = "completed"  # Action was taken within the window


@dataclass
class AOWWindow:
    """A time-bounded window for taking a governed action.

    The window has three key timestamps:
    - earliest: when the action becomes available
    - optimal: the ideal time (scheduling preference)
    - latest: hard deadline -- after this, the window expires

    Optionally, the window can be blocked by dependencies
    (other actions that must complete first).
    """

    action_id: str
    earliest: datetime
    optimal: datetime | None = None
    latest: datetime | None = None
    blocked_by: list[str] = field(default_factory=list)
    state: AOWState = AOWState.PENDING
    expiry_warning_minutes: int = 30
    metadata: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, now: datetime | None = None) -> AOWState:
        """Evaluate and update the current state of this window.

        Terminal states (EXPIRED, COMPLETED) are latched — once entered,
        the window cannot revert to an earlier state.

        If ``latest`` is None, the window has no expiration and stays
        OPEN indefinitely once ``earliest`` passes.
        """
        now = now or datetime.now(timezone.utc)

        # Terminal states are latched — once expired/completed, always so
        if self.state in (AOWState.EXPIRED, AOWState.COMPLETED):
            return self.state

        # Check blocked dependencies
        if self.blocked_by:
            self.state = AOWState.BLOCKED
            return self.state

        # Check temporal boundaries
        if now < self.earliest:
            self.state = AOWState.PENDING
            return self.state

        if self.latest and now > self.latest:
            self.state = AOWState.EXPIRED
            return self.state

        # Within window — check if expiring
        if self.latest:
            remaining = (self.latest - now).total_seconds() / 60
            if remaining <= self.expiry_warning_minutes:
                self.state = AOWState.EXPIRING
                return self.state

        # Check if in optimal sub-window
        if self.optimal:
            delta = abs((now - self.optimal).total_seconds()) / 60
            if delta <= 30:
                self.state = AOWState.OPTIMAL
                return self.state

        self.state = AOWState.OPEN
        return self.state

    def mark_completed(self) -> None:
        """Mark this window as completed (action was taken)."""
        self.state = AOWState.COMPLETED

    def add_blocker(self, action_id: str) -> None:
        """Add a blocking dependency."""
        if action_id not in self.blocked_by:
            self.blocked_by.append(action_id)

    def remove_blocker(self, action_id: str) -> None:
        """Remove a blocking dependency."""
        if action_id in self.blocked_by:
            self.blocked_by.remove(action_id)


class AOWHandler(GovernanceHandler):
    """Governance handler that enforces Action Opportunity Windows.

    If an action has an associated AOW window, this handler checks
    whether the window is open before allowing the action to proceed.

    AOW windows are looked up from context.metadata["aow_windows"],
    which should be a dict mapping action names to AOWWindow instances.
    """

    @property
    def name(self) -> str:
        return "aow_handler"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        windows = context.metadata.get("aow_windows", {})
        window = windows.get(context.action)

        if window is None:
            # No AOW constraint -- proceed
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason="No AOW window registered for this action",
            )

        state = window.evaluate()

        if state in (AOWState.OPEN, AOWState.OPTIMAL):
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"AOW window is {state.value}",
            )

        if state == AOWState.EXPIRING:
            # Allow but warn
            new_meta = dict(context.metadata)
            new_meta["aow_expiring"] = True
            modified = replace(context, metadata=new_meta)
            return GovernanceResult.modify(
                modified_context=modified,
                handler_name=self.name,
                reason="AOW window expiring -- action should be taken soon",
            )

        # PENDING, EXPIRED, BLOCKED -- block the action with structured feedback
        if state == AOWState.PENDING:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"AOW window is {state.value} -- action cannot proceed",
                suggestion=f"Action window opens at {window.earliest.isoformat()}. Schedule for then.",
                alternatives=[
                    "Wait for window",
                    "Request early access",
                ],
                recovery=RecoveryPlan(
                    primary=RecoveryAction.RETRY_AFTER_DELAY,
                    context={"opens_at": window.earliest.isoformat()},
                ),
            )

        if state == AOWState.EXPIRED:
            latest_str = window.latest.isoformat() if window.latest else "unknown"
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"AOW window is {state.value} -- action cannot proceed",
                suggestion=f"Action window closed at {latest_str}. Request a new window.",
                alternatives=[
                    "Request extension",
                    "Create new AOW",
                ],
                recovery=RecoveryPlan(
                    primary=RecoveryAction.DELEGATE_TO_HUMAN,
                    alternatives=[RecoveryAction.RETRY_WITH_APPROVAL],
                ),
            )

        # BLOCKED by dependencies
        blocked_by_list = window.blocked_by if window.blocked_by else []
        blocked_by = ", ".join(blocked_by_list) if blocked_by_list else "unknown"
        return GovernanceResult.abort(
            handler_name=self.name,
            reason=f"AOW window is {state.value} -- action cannot proceed",
            suggestion=f"Blocked by: {blocked_by}. Complete those first.",
            alternatives=[
                "Complete blockers first",
            ],
            recovery=RecoveryPlan(
                primary=RecoveryAction.RETRY_AFTER_DELAY,
                context={"blocked_by": blocked_by_list},
            ),
        )
