"""BudgetGatekeeper handler -- enforces cumulative cost limits."""

from __future__ import annotations

import logging
from typing import Callable

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)

logger = logging.getLogger(__name__)


class BudgetGatekeeper(GovernanceHandler):
    """Enforces cumulative API budget limits across all agent invocations.

    Accepts a cost_callback callable that returns the current cumulative
    cost in USD. If no callback is provided, checks context.metadata
    for a "current_cost_usd" key.

    Attributes:
        budget_limit_usd: Maximum allowed cumulative cost.
        cost_callback: Optional callable returning current cost as float.
    """

    def __init__(
        self,
        budget_limit_usd: float = 5.0,
        cost_callback: Callable[[], float] | None = None,
    ) -> None:
        self._budget_limit = budget_limit_usd
        self._cost_callback = cost_callback
        self._cumulative_cost: float = 0.0

    @property
    def name(self) -> str:
        return "budget_gatekeeper"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if self._cost_callback is not None:
            current = self._cost_callback()
        else:
            current = context.metadata.get("current_cost_usd", self._cumulative_cost)

        if current >= self._budget_limit:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Budget exceeded: ${current:.2f} >= ${self._budget_limit:.2f}",
            )

        return GovernanceResult.continue_(
            handler_name=self.name,
            reason=f"Budget OK: ${current:.2f} / ${self._budget_limit:.2f}",
        )

    def add_cost(self, amount: float) -> None:
        """Manually add cost to the internal tracker.

        Use this when not providing a cost_callback.
        """
        self._cumulative_cost += amount
