"""DynamicVTHandler -- replace static VT assignment with AMO water-filling.

Requires the [amo] extra: pip install governed-agents[amo]

Uses the minimal-oversight library to dynamically compute optimal VT
tier assignments based on pipeline topology and agent capabilities.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)

logger = logging.getLogger(__name__)

try:
    from minimal_oversight import analyze_pipeline  # type: ignore[import-untyped]
    from minimal_oversight.models import Node, PipelineGraph  # type: ignore[import-untyped]

    HAS_AMO = True
except ImportError:
    HAS_AMO = False
    analyze_pipeline = None
    Node = None
    PipelineGraph = None


class DynamicVTHandler(GovernanceHandler):
    """Replace static VT tier assignment with AMO water-filling optimization.

    When minimal-oversight is available, analyzes the pipeline graph and
    assigns optimal VT tiers that minimize oversight cost while maintaining
    safety guarantees.

    When minimal-oversight is not installed, passes through with the
    original VT tier unchanged.

    Attributes:
        safety_budget: Total safety budget to distribute across tiers (0.0-1.0).
        fallback_tier: VT tier to use when AMO is unavailable.
    """

    def __init__(
        self,
        safety_budget: float = 0.8,
        fallback_tier: int | None = None,
    ) -> None:
        self._safety_budget = safety_budget
        self._fallback_tier = fallback_tier

    @property
    def name(self) -> str:
        return "dynamic_vt"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if not HAS_AMO:
            if self._fallback_tier is not None:
                new_context = deepcopy(context)
                new_context.vt_tier = self._fallback_tier
                return GovernanceResult.modify(
                    modified_context=new_context,
                    handler_name=self.name,
                    reason=(
                        f"AMO not available, using fallback VT{self._fallback_tier}"
                    ),
                )
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason="AMO not available, keeping original VT tier",
            )

        try:
            # Build a simple pipeline graph for the current action
            node = Node(
                name=context.action,
                agent_id=context.agent_id or "unknown",
                capability_score=context.metadata.get("capability_score", 0.5),
            )
            graph = PipelineGraph(nodes=[node])
            result = analyze_pipeline(graph, budget=self._safety_budget)

            # Extract the optimized VT tier for this node
            optimized_tier = result.assignments.get(context.action, context.vt_tier)

            if optimized_tier != context.vt_tier:
                new_context = deepcopy(context)
                new_context.vt_tier = optimized_tier
                new_context.metadata["amo_original_vt"] = context.vt_tier
                new_context.metadata["amo_optimized_vt"] = optimized_tier
                return GovernanceResult.modify(
                    modified_context=new_context,
                    handler_name=self.name,
                    reason=(
                        f"AMO optimized: VT{context.vt_tier} -> VT{optimized_tier}"
                    ),
                )

            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"AMO confirms VT{context.vt_tier} is optimal",
            )

        except Exception as exc:
            logger.warning("DynamicVTHandler: AMO analysis failed: %s", exc)
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"AMO analysis failed, keeping VT{context.vt_tier}",
            )
