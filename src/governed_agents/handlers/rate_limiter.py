"""RateLimiter handler -- enforces bounded concurrency with sliding windows."""

from __future__ import annotations

import logging
import time

from governed_agents.config import RATE_LIMIT_MAX_CONCURRENT, RATE_LIMIT_WINDOW_S
from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)

logger = logging.getLogger(__name__)


class RateLimiter(GovernanceHandler):
    """Enforces bounded concurrency for pipeline actions.

    Uses a sliding window counter to limit the number of actions
    within a time window. Actions exceeding the limit are blocked.

    Attributes:
        max_per_window: Maximum actions allowed in the window.
        window_seconds: Sliding window duration in seconds.
    """

    def __init__(
        self,
        max_per_window: int | None = None,
        window_seconds: int | None = None,
        # Backward-compatible alias
        max_concurrent: int | None = None,
    ) -> None:
        effective = max_per_window or max_concurrent or RATE_LIMIT_MAX_CONCURRENT
        self._max_per_window = effective
        self._window_seconds = window_seconds or RATE_LIMIT_WINDOW_S
        self._timestamps: dict[str, list[float]] = {}

    @property
    def name(self) -> str:
        return "rate_limiter"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        now = time.time()
        cutoff = now - self._window_seconds
        agent_id = context.agent_id or "__global__"

        # Get or create per-agent timestamp list
        if agent_id not in self._timestamps:
            self._timestamps[agent_id] = []

        # Prune expired timestamps
        self._timestamps[agent_id] = [
            t for t in self._timestamps[agent_id] if t > cutoff
        ]

        if len(self._timestamps[agent_id]) >= self._max_per_window:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=(
                    f"Rate limit exceeded for {agent_id}: "
                    f"{len(self._timestamps[agent_id])}/{self._max_per_window} "
                    f"actions in {self._window_seconds}s window"
                ),
            )

        self._timestamps[agent_id].append(now)
        return GovernanceResult.continue_(
            handler_name=self.name,
            reason=(
                f"Rate OK for {agent_id}: "
                f"{len(self._timestamps[agent_id])}/{self._max_per_window}"
            ),
        )
