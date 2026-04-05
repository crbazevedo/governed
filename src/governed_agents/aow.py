"""Action Opportunity Windows -- time-bounded decision scheduling.

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


class AOWState(str, Enum):
    """Lifecycle state of an Action Opportunity Window."""

    PENDING = "pending"          # Window not yet open
    OPEN = "open"                # Within the window, action can be taken
    OPTIMAL = "optimal"          # Within the preferred sub-window
    EXPIRING = "expiring"        # Window closing soon (configurable threshold)
    EXPIRED = "expired"          # Window closed, action no longer possible
    BLOCKED = "blocked"          # Externally blocked (dependency not met)
    COMPLETED = "completed"      # Action was taken within the window


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
        """Evaluate the current state of this window."""
        now = now or datetime.now(timezone.utc)

        # Check blocked dependencies
        if self.blocked_by:
            return AOWState.BLOCKED

        # Check if completed
        if self.state == AOWState.COMPLETED:
            return AOWState.COMPLETED

        # Check temporal boundaries
        if now < self.earliest:
            return AOWState.PENDING

        if self.latest and now > self.latest:
            return AOWState.EXPIRED

        # Within window -- check if expiring
        if self.latest:
            remaining = (self.latest - now).total_seconds() / 60
            if remaining <= self.expiry_warning_minutes:
                return AOWState.EXPIRING

        # Check if in optimal sub-window
        if self.optimal:
            # Within 30 min of optimal time
            delta = abs((now - self.optimal).total_seconds()) / 60
            if delta <= 30:
                return AOWState.OPTIMAL

        return AOWState.OPEN

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

        # PENDING, EXPIRED, BLOCKED -- block the action
        return GovernanceResult.abort(
            handler_name=self.name,
            reason=f"AOW window is {state.value} -- action cannot proceed",
        )
