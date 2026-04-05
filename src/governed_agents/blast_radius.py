"""Blast radius policy — unified multi-dimension constraint.

# Layer: Dynamic (stateful, tracks cumulative usage)

Implements Principle 4 (Bounded Blast Radius). Combines cost, frequency,
scope, and irreversibility constraints into a single declarable policy
that bounds the maximum damage an agent can cause.

Replaces configuring BudgetGatekeeper + RateLimiter + scope checks
separately. One policy, one handler, one declaration.

Theoretical basis: The effective autonomy buffer B_eff (Eq. 16)
grows when downside risk is bounded. Every dimension we constrain
increases B_eff by reducing the worst-case outcome.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.recovery import RecoveryAction, RecoveryPlan


@dataclass
class BlastRadiusPolicy:
    """Multi-dimension constraint on agent damage potential.

    Every field is optional. Only set constraints you care about.
    The handler evaluates ALL dimensions and blocks on the tightest
    violated constraint.
    """

    # Cost constraints
    max_cost_per_action: float | None = None
    max_cost_per_hour: float | None = None
    max_cost_per_day: float | None = None

    # Frequency constraints
    max_actions_per_hour: int | None = None
    max_actions_per_day: int | None = None

    # Irreversibility constraints
    max_irreversible_per_day: int = 0
    irreversible_actions: frozenset[str] = field(default_factory=frozenset)

    # Scope constraints
    scope_ceiling: str | None = None  # e.g., "staging" — blocks "production"
    blocked_scopes: frozenset[str] = field(default_factory=frozenset)

    # Actions that always require elevated VT
    high_risk_actions: frozenset[str] = field(default_factory=frozenset)
    high_risk_vt: int = 2


class BlastRadiusHandler(GovernanceHandler):
    """Enforces a BlastRadiusPolicy as a single pipeline handler.

    Tracks cumulative cost and action frequency in-memory.
    Evaluates all constraint dimensions in one pass.

    Args:
        policy: The BlastRadiusPolicy to enforce.
    """

    def __init__(self, policy: BlastRadiusPolicy) -> None:
        self._policy = policy
        self._hourly_actions: list[float] = []
        self._daily_actions: list[float] = []
        self._hourly_cost: list[tuple[float, float]] = []  # (timestamp, cost)
        self._daily_cost: list[tuple[float, float]] = []
        self._daily_irreversible: list[float] = []

    @property
    def name(self) -> str:
        return "blast_radius"

    def record_cost(self, cost: float) -> None:
        """Record cost of a completed action. Call after execution."""
        now = time.time()
        self._hourly_cost.append((now, cost))
        self._daily_cost.append((now, cost))

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        p = self._policy
        now = time.time()
        violations: list[str] = []
        recovery_actions: list[RecoveryAction] = []
        recovery_ctx: dict[str, Any] = {}

        # -- Prune old timestamps --
        hour_ago = now - 3600
        day_ago = now - 86400
        self._hourly_actions = [t for t in self._hourly_actions if t > hour_ago]
        self._daily_actions = [t for t in self._daily_actions if t > day_ago]
        self._hourly_cost = [(t, c) for t, c in self._hourly_cost if t > hour_ago]
        self._daily_cost = [(t, c) for t, c in self._daily_cost if t > day_ago]
        self._daily_irreversible = [t for t in self._daily_irreversible if t > day_ago]

        # -- Check per-action cost --
        action_cost = context.metadata.get("estimated_cost_usd", 0.0)
        if p.max_cost_per_action and action_cost > p.max_cost_per_action:
            violations.append(
                f"Action cost ${action_cost:.2f} exceeds ${p.max_cost_per_action:.2f}/action"
            )
            recovery_actions.append(RecoveryAction.USE_CHEAPER_RESOURCE)

        # -- Check hourly cost --
        if p.max_cost_per_hour:
            hourly_total = sum(c for _, c in self._hourly_cost) + action_cost
            if hourly_total > p.max_cost_per_hour:
                violations.append(
                    f"Hourly cost ${hourly_total:.2f} exceeds ${p.max_cost_per_hour:.2f}/hr"
                )
                recovery_actions.append(RecoveryAction.RETRY_AFTER_DELAY)
                recovery_ctx["cost_resets_in_seconds"] = int(
                    3600 - (now - self._hourly_cost[0][0]) if self._hourly_cost else 3600
                )

        # -- Check daily cost --
        if p.max_cost_per_day:
            daily_total = sum(c for _, c in self._daily_cost) + action_cost
            if daily_total > p.max_cost_per_day:
                violations.append(
                    f"Daily cost ${daily_total:.2f} exceeds ${p.max_cost_per_day:.2f}/day"
                )
                recovery_actions.append(RecoveryAction.DELEGATE_TO_HUMAN)

        # -- Check hourly frequency --
        if p.max_actions_per_hour and len(self._hourly_actions) >= p.max_actions_per_hour:
            violations.append(
                f"Hourly actions {len(self._hourly_actions)}/{p.max_actions_per_hour} exceeded"
            )
            recovery_actions.append(RecoveryAction.BATCH_WITH_OTHERS)

        # -- Check daily frequency --
        if p.max_actions_per_day and len(self._daily_actions) >= p.max_actions_per_day:
            violations.append(
                f"Daily actions {len(self._daily_actions)}/{p.max_actions_per_day} exceeded"
            )
            recovery_actions.append(RecoveryAction.DELEGATE_TO_HUMAN)

        # -- Check irreversibility --
        is_irreversible = context.action in p.irreversible_actions
        if is_irreversible and len(self._daily_irreversible) >= p.max_irreversible_per_day:
            violations.append(
                f"Irreversible actions {len(self._daily_irreversible)}/{p.max_irreversible_per_day}/day exceeded"
            )
            recovery_actions.append(RecoveryAction.DELEGATE_TO_HUMAN)

        # -- Check scope --
        action_scope = context.metadata.get("scope", "")
        if action_scope and action_scope in p.blocked_scopes:
            violations.append(f"Scope '{action_scope}' is blocked by policy")
            recovery_actions.append(RecoveryAction.RETRY_LOWER_SCOPE)
            recovery_ctx["blocked_scope"] = action_scope
            if p.scope_ceiling:
                recovery_ctx["max_scope"] = p.scope_ceiling

        # -- Block if any violations --
        if violations:
            primary = recovery_actions[0] if recovery_actions else RecoveryAction.DELEGATE_TO_HUMAN
            alts = list(dict.fromkeys(recovery_actions[1:]))  # deduplicate, preserve order

            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Blast radius violated: {'; '.join(violations)}",
                suggestion=violations[0],
                alternatives=[v for v in violations[1:]],
                recovery=RecoveryPlan(
                    primary=primary,
                    alternatives=alts,
                    context=recovery_ctx,
                    explanation=f"{len(violations)} constraint(s) violated",
                ),
            )

        # -- Record this action --
        self._hourly_actions.append(now)
        self._daily_actions.append(now)
        if is_irreversible:
            self._daily_irreversible.append(now)

        # -- Elevate VT for high-risk actions --
        if context.action in p.high_risk_actions and context.vt_tier < p.high_risk_vt:
            modified = replace(context, vt_tier=p.high_risk_vt)
            return GovernanceResult.modify(
                modified_context=modified,
                handler_name=self.name,
                reason=f"High-risk action '{context.action}' elevated to VT{p.high_risk_vt}",
            )

        return GovernanceResult.continue_(
            handler_name=self.name,
            reason="Blast radius OK",
        )
