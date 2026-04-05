"""Domain-scoped governance for BYOPA (Bring Your Own Personal Agent).

Enables the same governance library to enforce different policies
in different domains (e.g., personal vs corporate), with information
barriers preventing content leakage across domain boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)


class DomainScope(str, Enum):
    """Standard domain scopes."""

    PERSONAL = "personal"
    CORPORATE = "corporate"
    SHARED = "shared"  # Metadata-only cross-domain


@dataclass
class GovernanceProfile:
    """Domain-specific governance configuration.

    Each domain has its own VT ceiling map (action -> max VT tier),
    allowed/blocked tools, PII sensitivity level, and audit requirements.
    """

    domain: str
    vt_ceiling: dict[str, int] = field(default_factory=dict)  # action -> max VT
    default_vt: int = 2
    allowed_tools: set[str] | None = None  # None = all allowed
    blocked_tools: set[str] = field(default_factory=set)
    pii_sensitivity: int = 1  # 0=low, 1=standard, 2=high (health/financial)
    audit_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_vt_ceiling(self, action: str) -> int:
        """Get the VT ceiling for an action in this domain."""
        return self.vt_ceiling.get(action, self.default_vt)

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed in this domain."""
        if tool_name in self.blocked_tools:
            return False
        if self.allowed_tools is not None:
            return tool_name in self.allowed_tools
        return True


# Metadata fields allowed to cross domain boundaries
CROSS_DOMAIN_ALLOWED_FIELDS = frozenset(
    {
        "timestamp",
        "duration_minutes",
        "participant_count",
        "urgency",
        "domain_scope",
        "action_type",
    }
)


class DomainBarrierHandler(GovernanceHandler):
    """Enforces information barriers between governance domains.

    Prevents content from one domain leaking into another.
    Only metadata fields in CROSS_DOMAIN_ALLOWED_FIELDS can
    cross the barrier.
    """

    def __init__(
        self,
        profiles: dict[str, GovernanceProfile] | None = None,
        allowed_fields: frozenset[str] = CROSS_DOMAIN_ALLOWED_FIELDS,
    ):
        self._profiles = profiles or {}
        self._allowed_fields = allowed_fields

    @property
    def name(self) -> str:
        return "domain_barrier"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        domain = context.metadata.get("domain_scope")
        target_domain = context.metadata.get("target_domain")

        # No cross-domain activity -- pass through
        if not domain or not target_domain or domain == target_domain:
            # Apply domain profile VT ceiling if available
            profile = self._profiles.get(domain, None) if domain else None
            if profile:
                ceiling = profile.get_vt_ceiling(context.action)
                if context.vt_tier < ceiling:
                    modified = replace(context, vt_tier=ceiling)
                    return GovernanceResult.modify(
                        modified_context=modified,
                        handler_name=self.name,
                        reason=f"Domain {domain} requires VT{ceiling} for {context.action}",
                    )
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason="No cross-domain activity",
            )

        # Cross-domain: filter payload to allowed fields only
        filtered_payload = {
            k: v for k, v in context.payload.items() if k in self._allowed_fields
        }
        blocked_fields = set(context.payload.keys()) - self._allowed_fields

        if blocked_fields:
            new_meta = dict(context.metadata)
            new_meta["blocked_fields"] = list(blocked_fields)
            new_meta["cross_domain"] = True
            modified = replace(
                context,
                payload=filtered_payload,
                metadata=new_meta,
            )
            return GovernanceResult.modify(
                modified_context=modified,
                handler_name=self.name,
                reason=f"Cross-domain barrier: {len(blocked_fields)} fields filtered, "
                f"{len(filtered_payload)} fields passed (metadata only)",
            )

        return GovernanceResult.continue_(
            handler_name=self.name,
            reason="Cross-domain payload contains only allowed metadata fields",
        )
