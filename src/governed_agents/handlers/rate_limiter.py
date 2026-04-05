"""RateLimiter handler -- enforces action frequency limits.

# Layer: Dynamic (stateful, in-memory by default)

Accepts a pluggable RateLimitPolicy backend. Built-in InMemoryRateLimit
is used by default (sliding window, single-process). For distributed
systems, plug in a Redis-backed or API gateway rate limiter.
"""

from __future__ import annotations

import logging
import time

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.interfaces import RateLimitPolicy
from governed_agents.recovery import RecoveryAction, RecoveryPlan

logger = logging.getLogger(__name__)


class InMemoryRateLimit(RateLimitPolicy):
    """Built-in sliding window rate limiter. Single-process only.

    For distributed rate limiting, implement ``RateLimitPolicy``
    with Redis, a token bucket, or your API gateway's rate limiter.
    """

    def __init__(self, max_per_window: int = 5, window_seconds: int = 60) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}

    async def check(self, agent_id: str, action: str) -> bool:
        now = time.time()
        cutoff = now - self._window
        key = agent_id or "__global__"
        ts = self._timestamps.get(key, [])
        ts = [t for t in ts if t > cutoff]
        self._timestamps[key] = ts
        return len(ts) < self._max

    async def record(self, agent_id: str, action: str) -> None:
        key = agent_id or "__global__"
        self._timestamps.setdefault(key, []).append(time.time())

    def seconds_until_slot(self, agent_id: str) -> float:
        """Return seconds until the oldest timestamp exits the window.

        Returns 0.0 if a slot is already available.
        """
        now = time.time()
        cutoff = now - self._window
        key = agent_id or "__global__"
        ts = [t for t in self._timestamps.get(key, []) if t > cutoff]
        if len(ts) < self._max:
            return 0.0
        # Oldest timestamp in window -- wait for it to expire
        oldest = min(ts)
        return max(oldest + self._window - now, 0.0)


class RateLimiter(GovernanceHandler):
    """Enforces action frequency limits via a pluggable policy.

    Args:
        policy: RateLimitPolicy implementation. Defaults to InMemoryRateLimit.
        max_per_window: Max actions in window (forwarded to default policy).
        window_seconds: Window duration (forwarded to default policy).
    """

    def __init__(
        self,
        policy: RateLimitPolicy | None = None,
        max_per_window: int = 5,
        window_seconds: int = 60,
        # Backward compat
        max_concurrent: int | None = None,
    ) -> None:
        if policy is not None:
            self._policy = policy
        else:
            effective_max = max_per_window if max_concurrent is None else max_concurrent
            self._policy = InMemoryRateLimit(effective_max, window_seconds)

    @property
    def name(self) -> str:
        return "rate_limiter"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        allowed = await self._policy.check(context.agent_id, context.action)

        if not allowed:
            # Compute wait time if the policy supports it
            wait_hint = ""
            delay_seconds: float = 0.0
            if isinstance(self._policy, InMemoryRateLimit):
                delay_seconds = self._policy.seconds_until_slot(context.agent_id)
                wait_hint = f"Wait {delay_seconds:.0f}s before retrying"
            else:
                wait_hint = "Wait for the current rate limit window to clear"

            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Rate limit exceeded for '{context.agent_id}'",
                suggestion=wait_hint,
                alternatives=[
                    "Reduce action frequency",
                    "Batch actions",
                ],
                recovery=RecoveryPlan(
                    primary=RecoveryAction.RETRY_AFTER_DELAY,
                    alternatives=[RecoveryAction.BATCH_WITH_OTHERS],
                    context={"delay_seconds": delay_seconds},
                ),
            )

        await self._policy.record(context.agent_id, context.action)
        return GovernanceResult.continue_(
            handler_name=self.name,
            reason=f"Rate OK for '{context.agent_id}'",
        )
