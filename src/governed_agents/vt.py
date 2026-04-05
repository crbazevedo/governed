"""VT (Verified Trust) governance tier system.

Implements the five-tier governance model for agent autonomy:
    VT0 (auto):    Agent acts freely -- no restrictions.
    VT1 (log):     Agent acts, action logged for review.
    VT2 (approve): Agent proposes, human approves before execution.
    VT3 (advise):  Agent advises only -- cannot execute.
    VT4 (block):   Owner-only action -- fully blocked for agents.

Provides:
- VTTier enum with labels and policy keywords
- VTPolicy dataclass for per-tier configuration
- VTGovernanceHandler for pipeline integration
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from enum import IntEnum

from governed_agents.config import VT_TIERS
from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)

logger = logging.getLogger(__name__)


class VTTier(IntEnum):
    """VT risk tier levels."""

    AUTO = 0      # Agent acts freely
    LOG = 1       # Agent acts, logs for review
    APPROVE = 2   # Agent proposes, owner approves
    ADVISE = 3    # Agent advises only
    BLOCK = 4     # Owner-only action

    @property
    def label(self) -> str:
        """Human-readable label for this tier."""
        labels = {
            0: "Autonomous",
            1: "Log & Proceed",
            2: "Require Approval",
            3: "Advise Only",
            4: "Owner Only",
        }
        return labels.get(self.value, "Unknown")

    @property
    def policy(self) -> str:
        """Policy keyword for this tier."""
        policies = {
            0: "auto",
            1: "log",
            2: "approve",
            3: "advise",
            4: "block",
        }
        return policies.get(self.value, "block")


@dataclass
class VTPolicy:
    """Policy configuration for a VT tier.

    Attributes:
        tier: The VT tier level.
        action: Policy keyword (auto, log, approve, advise, block).
        label: Human-readable label.
        requires_approval: Whether human approval is needed.
        allows_execution: Whether the agent can execute the action.
    """

    tier: int
    action: str
    label: str
    requires_approval: bool = False
    allows_execution: bool = True

    @classmethod
    def for_tier(cls, tier: int) -> VTPolicy:
        """Create a VTPolicy for the given tier number."""
        configs = {
            0: cls(tier=0, action="auto", label="Autonomous"),
            1: cls(tier=1, action="log", label="Log & Proceed"),
            2: cls(
                tier=2, action="approve", label="Require Approval",
                requires_approval=True,
            ),
            3: cls(
                tier=3, action="advise", label="Advise Only",
                allows_execution=False,
            ),
            4: cls(
                tier=4, action="block", label="Owner Only",
                requires_approval=True, allows_execution=False,
            ),
        }
        return configs.get(tier, cls(
            tier=tier, action="block", label="Unknown",
            requires_approval=True, allows_execution=False,
        ))


class VTGovernanceHandler(GovernanceHandler):
    """Validates actions against VT tier governance rules.

    VT tier enforcement:
        VT0 (auto):    Allow -- agent acts freely.
        VT1 (log):     Allow and log -- agent acts, flagged for review.
        VT2 (approve): Block unless metadata["vt2_approved"] is True.
        VT3 (advise):  Always block -- agent may only advise.
        VT4 (block):   Always block -- owner-only action.
    """

    @property
    def name(self) -> str:
        return "vt_governance"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        vt = context.vt_tier
        tier_policy = VT_TIERS.get(vt, "block")

        if tier_policy == "auto":
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"VT{vt}: auto-approved -- no restrictions",
            )

        if tier_policy == "log":
            # Inject review metadata for downstream handlers
            new_context = deepcopy(context)
            new_context.metadata["governance_review_required"] = True
            new_context.metadata["governance_vt_tier"] = vt
            new_context.metadata["governance_policy"] = tier_policy
            logger.info(
                "VTGovernance: VT%d action '%s' by '%s' -- logged for review",
                vt, context.action, context.agent_id,
            )
            return GovernanceResult.modify(
                modified_context=new_context,
                handler_name=self.name,
                reason=f"VT{vt}: allowed with review flag",
            )

        if tier_policy == "approve":
            if context.metadata.get("vt2_approved"):
                new_context = deepcopy(context)
                new_context.metadata["governance_approval_verified"] = True
                new_context.metadata["governance_vt_tier"] = vt
                return GovernanceResult.modify(
                    modified_context=new_context,
                    handler_name=self.name,
                    reason=f"VT{vt}: pre-approved by owner",
                )
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=(
                    f"VT{vt}: requires owner approval. "
                    f"Set metadata['vt2_approved']=True after owner confirms. "
                    f"Action: '{context.action}', Agent: '{context.agent_id}'"
                ),
            )

        if tier_policy == "advise":
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=(
                    f"VT{vt}: agent may only advise, not act. "
                    f"Escalate to owner for execution. "
                    f"Action: '{context.action}', Agent: '{context.agent_id}'"
                ),
            )

        # VT4 or unknown -- always block
        return GovernanceResult.abort(
            handler_name=self.name,
            reason=(
                f"VT{vt}: owner-only action -- blocked. "
                f"This action cannot be delegated to agents. "
                f"Action: '{context.action}', Agent: '{context.agent_id}'"
            ),
        )
