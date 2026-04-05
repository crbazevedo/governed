"""DynamicVTHandler -- replace static VT assignment with AMO-driven allocation.

# Layer: Persistent (requires minimal-oversight, optional integration)

Uses the Axiom of Minimal Oversight (AMO) from the minimal-oversight library
to dynamically compute optimal authority allocation. Instead of static VT tiers
per action, the AMO water-filling solution concentrates oversight where the
marginal return is highest (moderate-competence agents, not weak or strong ones).

Requires: pip install governed-agents[amo]

Reference:
    Azevedo, C.R.B. (2026). "Minimal Oversight: A Theory of Principled
    Autonomy Delegation." arXiv:submit/7429273.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)

logger = logging.getLogger(__name__)

try:
    from minimal_oversight import analyze_pipeline
    from minimal_oversight.models import Node, PipelineGraph, GovernancePolicy

    HAS_AMO = True
except ImportError:
    HAS_AMO = False
    analyze_pipeline = None  # type: ignore[assignment]
    Node = None  # type: ignore[assignment,misc]
    PipelineGraph = None  # type: ignore[assignment,misc]
    GovernancePolicy = None  # type: ignore[assignment,misc]


def _authority_to_vt(authority: float) -> int:
    """Map a continuous authority allocation α ∈ [0,1] to a discrete VT tier.

    The AMO's water-filling solution produces continuous α values.
    We discretize into VT tiers:
        α >= 0.8  → VT0 (autonomous: agent is highly competent here)
        α >= 0.5  → VT1 (log: moderate competence, light oversight)
        α >= 0.2  → VT2 (approve: needs review)
        α >= 0.05 → VT3 (advise: low competence, advisory only)
        α < 0.05  → VT4 (block: agent should not act here)
    """
    if authority >= 0.8:
        return 0
    if authority >= 0.5:
        return 1
    if authority >= 0.2:
        return 2
    if authority >= 0.05:
        return 3
    return 4


class DynamicVTHandler(GovernanceHandler):
    """Replace static VT tiers with AMO-optimized authority allocation.

    The handler builds a single-node pipeline graph representing the current
    action's agent, computes the AMO report, and maps the optimal authority
    allocation to a VT tier. This replaces the static VT assignment with a
    principled, information-theoretic allocation.

    When minimal-oversight is not installed, the handler passes through
    with the original VT tier (or applies a configurable fallback).

    Args:
        p_min: Minimum acceptable quality target (0.0-1.0). Higher means
            more oversight. Default 0.80.
        fallback_tier: VT tier to use when AMO is unavailable. If None,
            the original context VT tier is preserved.

    Metadata inputs (from ActionContext.metadata):
        sigma_skill: Agent's competence for this action (0.0-1.0).
            Defaults to 0.5 if not provided.
        catch_rate: Corrector's error-catch probability (0.0-1.0).
            Defaults to 0.65 if not provided.
    """

    def __init__(
        self,
        p_min: float = 0.80,
        fallback_tier: int | None = None,
    ) -> None:
        self._p_min = p_min
        self._fallback_tier = fallback_tier

    @property
    def name(self) -> str:
        return "dynamic_vt"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if not HAS_AMO:
            if self._fallback_tier is not None:
                modified = replace(context, vt_tier=self._fallback_tier)
                return GovernanceResult.modify(
                    modified_context=modified,
                    handler_name=self.name,
                    reason=f"AMO not available, using fallback VT{self._fallback_tier}",
                )
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason="AMO not available, keeping original VT tier",
            )

        try:
            # Extract agent capability signals from context metadata
            sigma_skill = context.metadata.get("sigma_skill", 0.5)
            catch_rate = context.metadata.get("catch_rate", 0.65)

            # Build a single-node pipeline graph for AMO analysis
            node = Node(
                name=context.action,
                sigma_skill=sigma_skill,
                catch_rate=catch_rate,
            )
            graph = PipelineGraph(nodes=[node])

            # Run AMO analysis
            report = analyze_pipeline(graph, p_min=self._p_min)

            # Extract authority allocation from the feasibility report
            # The AMO computes operational capacity and effective autonomy buffer
            c_op = report.feasibility.c_op
            b_eff = report.feasibility.b_eff

            # Map capacity to authority: higher capacity → more autonomy
            # authority = capacity normalized to [0, 1]
            authority = max(0.0, min(1.0, c_op))
            optimized_tier = _authority_to_vt(authority)

            if optimized_tier != context.vt_tier:
                new_meta = {
                    **context.metadata,
                    "amo_original_vt": context.vt_tier,
                    "amo_optimized_vt": optimized_tier,
                    "amo_authority": round(authority, 3),
                    "amo_capacity": round(c_op, 3),
                    "amo_buffer": round(b_eff, 3) if b_eff is not None else None,
                    "amo_feasible": report.feasibility.is_feasible,
                }
                modified = replace(context, vt_tier=optimized_tier, metadata=new_meta)
                return GovernanceResult.modify(
                    modified_context=modified,
                    handler_name=self.name,
                    reason=(
                        f"AMO: VT{context.vt_tier}→VT{optimized_tier} "
                        f"(authority={authority:.2f}, capacity={c_op:.2f}, "
                        f"feasible={report.feasibility.is_feasible})"
                    ),
                )

            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"AMO confirms VT{context.vt_tier} is optimal (authority={authority:.2f})",
            )

        except Exception as exc:
            logger.warning("DynamicVTHandler: AMO analysis failed: %s", exc)
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"AMO analysis failed ({exc}), keeping VT{context.vt_tier}",
                suggestion="Check minimal-oversight installation and agent metadata",
            )
