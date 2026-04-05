"""BudgetGatekeeper handler -- enforces cumulative cost limits.

# Layer: Dynamic (stateful governance decision)

Accepts a pluggable CostProvider backend for retrieving current spend.
Built-in ManualCostTracker is used by default. For production, plug in
litellm callbacks, LangSmith, Helicone, or any CostProvider implementation.

The BLOCKING LOGIC is the governance value-add. The cost tracking is
infrastructure that belongs to the consumer.
"""

from __future__ import annotations

import logging

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.interfaces import CostProvider
from governed_agents.recovery import RecoveryAction, RecoveryPlan

logger = logging.getLogger(__name__)


class ManualCostTracker(CostProvider):
    """Built-in cost tracker with manual add_cost() calls.

    For production, implement ``CostProvider`` with litellm's
    cost tracking callbacks, LangSmith, Helicone, or your billing system.
    """

    def __init__(self) -> None:
        self._costs: dict[str, float] = {}
        self._total: float = 0.0

    def current_cost(self, agent_id: str | None = None) -> float:
        if agent_id:
            return self._costs.get(agent_id, 0.0)
        return self._total

    def add_cost(self, amount: float, agent_id: str = "__global__") -> None:
        """Record a cost. Called by the consuming application after each LLM call."""
        self._costs[agent_id] = self._costs.get(agent_id, 0.0) + amount
        self._total += amount


class BudgetGatekeeper(GovernanceHandler):
    """Blocks actions when cumulative cost exceeds budget.

    The governance decision (should this action proceed given the budget?)
    is ours. The cost data source is pluggable via CostProvider.

    Args:
        budget_limit_usd: Maximum allowed cumulative cost.
        cost_provider: CostProvider implementation. Defaults to ManualCostTracker.
    """

    def __init__(
        self,
        budget_limit_usd: float = 5.0,
        cost_provider: CostProvider | None = None,
        # Backward compat: accept a simple callable
        cost_callback: None = None,
    ) -> None:
        self._budget_limit = budget_limit_usd
        if cost_provider is not None:
            self._provider = cost_provider
        else:
            self._provider = ManualCostTracker()

    @property
    def name(self) -> str:
        return "budget_gatekeeper"

    @property
    def cost_provider(self) -> CostProvider:
        """Access the cost provider (e.g., to call add_cost on ManualCostTracker)."""
        return self._provider

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        current = self._provider.current_cost(context.agent_id)

        if current >= self._budget_limit:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Budget exceeded: ${current:.2f} >= ${self._budget_limit:.2f}",
                suggestion="Reduce cost by using a cheaper model or smaller context",
                alternatives=[
                    "Use a lighter model",
                    "Batch with other requests",
                    "Request budget increase",
                ],
                recovery=RecoveryPlan(
                    primary=RecoveryAction.USE_CHEAPER_RESOURCE,
                    alternatives=[
                        RecoveryAction.BATCH_WITH_OTHERS,
                        RecoveryAction.DELEGATE_TO_HUMAN,
                    ],
                    context={
                        "current_cost": current,
                        "limit": self._budget_limit,
                    },
                ),
            )

        return GovernanceResult.continue_(
            handler_name=self.name,
            reason=f"Budget OK: ${current:.2f} / ${self._budget_limit:.2f}",
        )

    def add_cost(self, amount: float, agent_id: str = "__global__") -> None:
        """Convenience: add cost to the default ManualCostTracker.

        Raises TypeError if the provider is not a ManualCostTracker.
        """
        if isinstance(self._provider, ManualCostTracker):
            self._provider.add_cost(amount, agent_id)
        else:
            raise TypeError(
                f"add_cost() requires ManualCostTracker, got {type(self._provider).__name__}. "
                "Record costs through your CostProvider implementation instead."
            )
