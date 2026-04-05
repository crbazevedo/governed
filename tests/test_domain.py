"""Tests for Domain governance (BYOPA)."""

from __future__ import annotations

from governed_agents.domain import (
    CROSS_DOMAIN_ALLOWED_FIELDS,
    DomainBarrierHandler,
    DomainScope,
    GovernanceProfile,
)
from governed_agents.handler import ActionContext, Verdict


# ── DomainScope enum ─────────────────────────────────────────────────


class TestDomainScope:
    def test_values(self):
        assert DomainScope.PERSONAL == "personal"
        assert DomainScope.CORPORATE == "corporate"
        assert DomainScope.SHARED == "shared"

    def test_count(self):
        assert len(DomainScope) == 3


# ── GovernanceProfile ────────────────────────────────────────────────


class TestGovernanceProfile:
    def test_default_vt_floor(self):
        profile = GovernanceProfile(domain="personal")
        assert profile.get_vt_floor("anything") == 2  # default_vt

    def test_custom_vt_floor(self):
        profile = GovernanceProfile(
            domain="corporate",
            vt_floor={"deploy": 3, "read": 0},
            default_vt=2,
        )
        assert profile.get_vt_floor("deploy") == 3
        assert profile.get_vt_floor("read") == 0
        assert profile.get_vt_floor("unknown") == 2

    def test_tool_allowed_when_no_restrictions(self):
        profile = GovernanceProfile(domain="personal")
        assert profile.is_tool_allowed("any_tool") is True

    def test_tool_allowed_in_allowlist(self):
        profile = GovernanceProfile(
            domain="corporate",
            allowed_tools={"slack", "jira"},
        )
        assert profile.is_tool_allowed("slack") is True
        assert profile.is_tool_allowed("personal_email") is False

    def test_tool_blocked(self):
        profile = GovernanceProfile(
            domain="corporate",
            blocked_tools={"personal_email"},
        )
        assert profile.is_tool_allowed("personal_email") is False
        assert profile.is_tool_allowed("slack") is True

    def test_blocked_takes_priority_over_allowed(self):
        profile = GovernanceProfile(
            domain="corporate",
            allowed_tools={"slack", "personal_email"},
            blocked_tools={"personal_email"},
        )
        assert profile.is_tool_allowed("personal_email") is False

    def test_metadata_field(self):
        profile = GovernanceProfile(
            domain="personal",
            metadata={"owner": "carlos"},
        )
        assert profile.metadata["owner"] == "carlos"


# ── DomainBarrierHandler ─────────────────────────────────────────────


class TestDomainBarrierHandler:
    async def test_no_domain_passes_through(self):
        handler = DomainBarrierHandler()
        ctx = ActionContext(action="read", agent_id="eng")
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_same_domain_passes_through(self):
        handler = DomainBarrierHandler()
        ctx = ActionContext(
            action="read",
            agent_id="eng",
            metadata={"domain_scope": "personal", "target_domain": "personal"},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_cross_domain_filters_payload(self):
        handler = DomainBarrierHandler()
        ctx = ActionContext(
            action="share",
            agent_id="eng",
            payload={
                "timestamp": "2026-04-04T12:00:00Z",
                "urgency": "high",
                "meeting_notes": "Confidential content here",
                "attendees": ["alice", "bob"],
            },
            metadata={
                "domain_scope": "personal",
                "target_domain": "corporate",
            },
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context is not None
        # Allowed fields pass through
        assert "timestamp" in result.modified_context.payload
        assert "urgency" in result.modified_context.payload
        # Blocked fields are removed from payload
        assert "meeting_notes" not in result.modified_context.payload
        assert "attendees" not in result.modified_context.payload
        # Blocked fields recorded in metadata
        assert "meeting_notes" in result.modified_context.metadata["blocked_fields"]
        assert result.modified_context.metadata["cross_domain"] is True

    async def test_cross_domain_all_allowed_fields(self):
        handler = DomainBarrierHandler()
        ctx = ActionContext(
            action="share",
            agent_id="eng",
            payload={
                "timestamp": "2026-04-04T12:00:00Z",
                "urgency": "low",
            },
            metadata={
                "domain_scope": "personal",
                "target_domain": "corporate",
            },
        )
        result = await handler.evaluate(ctx)
        # All fields are allowed, so ALLOW (not MODIFY)
        assert result.action == Verdict.ALLOW

    async def test_domain_profile_vt_floor_applied(self):
        profile = GovernanceProfile(
            domain="corporate",
            vt_floor={"deploy": 3},
            default_vt=2,
        )
        handler = DomainBarrierHandler(profiles={"corporate": profile})
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            vt_tier=1,
            metadata={"domain_scope": "corporate"},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.vt_tier == 3

    async def test_domain_profile_no_elevation_when_at_floor(self):
        profile = GovernanceProfile(
            domain="corporate",
            vt_floor={"deploy": 2},
            default_vt=2,
        )
        handler = DomainBarrierHandler(profiles={"corporate": profile})
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            vt_tier=2,
            metadata={"domain_scope": "corporate"},
        )
        result = await handler.evaluate(ctx)
        # vt_tier == floor, no modification needed
        assert result.action == Verdict.ALLOW

    async def test_custom_allowed_fields(self):
        custom_fields = frozenset({"timestamp", "custom_field"})
        handler = DomainBarrierHandler(allowed_fields=custom_fields)
        ctx = ActionContext(
            action="share",
            agent_id="eng",
            payload={
                "timestamp": "2026-04-04T12:00:00Z",
                "urgency": "high",  # Not in custom set
                "custom_field": "value",
            },
            metadata={
                "domain_scope": "personal",
                "target_domain": "corporate",
            },
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert "urgency" in result.modified_context.metadata["blocked_fields"]
        assert "timestamp" in result.modified_context.payload
        assert "custom_field" in result.modified_context.payload

    def test_cross_domain_allowed_fields_constant(self):
        """Verify the default allowed fields set."""
        assert "timestamp" in CROSS_DOMAIN_ALLOWED_FIELDS
        assert "duration_minutes" in CROSS_DOMAIN_ALLOWED_FIELDS
        assert "urgency" in CROSS_DOMAIN_ALLOWED_FIELDS
        assert "domain_scope" in CROSS_DOMAIN_ALLOWED_FIELDS
        assert "action_type" in CROSS_DOMAIN_ALLOWED_FIELDS
        # participant_count deliberately excluded (could reveal meeting sensitivity)
        assert "participant_count" not in CROSS_DOMAIN_ALLOWED_FIELDS
