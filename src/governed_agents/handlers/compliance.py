"""ComplianceChecker handler -- validates payload size, VT consistency, audit readiness.

# Layer: Static (stateless governance handler)

Checks that agent actions meet structural governance requirements
before execution: payload size limits, audit trail readiness, and
VT tier consistency. Catches configuration errors (like mismatched
VT tiers) early, before they cause confusing downstream failures.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from governed_agents.config import MAX_PAYLOAD_SIZE_KB
from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.recovery import RecoveryAction, RecoveryPlan

logger = logging.getLogger(__name__)


class ComplianceChecker(GovernanceHandler):
    """Validates that the action output meets governance standards.

    Checks performed:
    1. Payload size limit -- rejects payloads exceeding max_payload_kb.
    2. Audit readiness -- verifies audit trail fields are present for VT1+.
    3. VT tier consistency -- action's stated VT tier matches governance context.

    Attributes:
        max_payload_kb: Maximum allowed payload size in KB.
        strict_mode: If True, abort on any compliance failure.
                     If False, log warnings but continue.
    """

    def __init__(
        self,
        max_payload_kb: int | None = None,
        strict_mode: bool = True,
    ) -> None:
        self._max_payload_kb = max_payload_kb or MAX_PAYLOAD_SIZE_KB
        self._strict_mode = strict_mode

    @property
    def name(self) -> str:
        return "compliance_checker"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        violations: list[str] = []

        # Check 1: Payload size
        payload_size = self._estimate_payload_size(context.payload)
        max_bytes = self._max_payload_kb * 1024
        if payload_size > max_bytes:
            violations.append(
                f"Payload size {payload_size} bytes exceeds limit "
                f"of {max_bytes} bytes ({self._max_payload_kb} KB)"
            )

        # Check 2: Audit readiness for VT1+
        if context.vt_tier >= 1:
            if not context.agent_id:
                violations.append("VT1+ actions require agent_id for audit trail")
            if not context.action:
                violations.append("VT1+ actions require action name for audit trail")

        # Check 3: VT consistency with governance metadata
        gov_vt = context.metadata.get("governance_vt_tier")
        if gov_vt is not None and gov_vt != context.vt_tier:
            violations.append(
                f"VT tier mismatch: context says VT{context.vt_tier} but governance set VT{gov_vt}"
            )

        if not violations:
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason="All compliance checks passed",
            )

        violation_msg = "; ".join(violations)

        if self._strict_mode:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"Compliance violations: {violation_msg}",
                suggestion="Fix the listed violations and retry",
                alternatives=[v for v in violations],
                recovery=RecoveryPlan(
                    primary=RecoveryAction.RETRY_LOWER_SCOPE,
                    alternatives=[RecoveryAction.DELEGATE_TO_HUMAN],
                    explanation=f"{len(violations)} compliance violation(s) detected",
                ),
            )

        # Non-strict: log and continue
        logger.warning("ComplianceChecker: non-strict violations: %s", violation_msg)
        new_metadata = {**context.metadata, "compliance_warnings": violations}
        modified = replace(context, metadata=new_metadata)
        return GovernanceResult.modify(
            modified_context=modified,
            handler_name=self.name,
            reason=f"Compliance warnings (non-strict): {violation_msg}",
        )

    @staticmethod
    def _estimate_payload_size(payload: dict[str, Any]) -> int:
        """Estimate payload size in bytes using repr length."""
        return len(repr(payload).encode("utf-8"))
