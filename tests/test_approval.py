"""Tests for Approval protocol models."""

from __future__ import annotations

from governed_agents.approval import (
    ApprovalBackend,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
)


class TestApprovalStatus:
    def test_all_statuses_exist(self):
        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.DENIED == "denied"
        assert ApprovalStatus.DEFERRED == "deferred"
        assert ApprovalStatus.TIMED_OUT == "timed_out"

    def test_status_count(self):
        assert len(ApprovalStatus) == 5


class TestApprovalRequest:
    def test_required_fields(self):
        req = ApprovalRequest(
            trace_id="T001",
            action="deploy_prod",
            agent_id="eng",
            vt_tier=2,
            summary="Deploy v3.0 to production",
        )
        assert req.trace_id == "T001"
        assert req.action == "deploy_prod"
        assert req.agent_id == "eng"
        assert req.vt_tier == 2
        assert req.summary == "Deploy v3.0 to production"

    def test_defaults(self):
        req = ApprovalRequest(
            trace_id="T001",
            action="deploy",
            agent_id="eng",
            vt_tier=2,
            summary="Deploy",
        )
        assert req.body == ""
        assert req.options is None
        assert req.timeout_seconds == 1800
        assert req.metadata == {}

    def test_custom_fields(self):
        req = ApprovalRequest(
            trace_id="T001",
            action="deploy",
            agent_id="eng",
            vt_tier=3,
            summary="Deploy",
            body="Full details here",
            options=["approve", "deny", "defer"],
            timeout_seconds=600,
            metadata={"priority": "high"},
        )
        assert req.body == "Full details here"
        assert req.options == ["approve", "deny", "defer"]
        assert req.timeout_seconds == 600
        assert req.metadata["priority"] == "high"


class TestApprovalResponse:
    def test_approved_response(self):
        resp = ApprovalResponse(
            trace_id="T001",
            status=ApprovalStatus.APPROVED,
            responded_by="carlos",
            rationale="Looks good",
        )
        assert resp.status == ApprovalStatus.APPROVED
        assert resp.responded_by == "carlos"
        assert resp.rationale == "Looks good"

    def test_denied_response(self):
        resp = ApprovalResponse(
            trace_id="T001",
            status=ApprovalStatus.DENIED,
            rationale="Too risky",
        )
        assert resp.status == ApprovalStatus.DENIED

    def test_defaults(self):
        resp = ApprovalResponse(
            trace_id="T001",
            status=ApprovalStatus.PENDING,
        )
        assert resp.responded_by == ""
        assert resp.rationale == ""
        assert resp.metadata == {}


class TestApprovalBackend:
    def test_is_abstract(self):
        """ApprovalBackend cannot be instantiated directly."""
        import pytest

        with pytest.raises(TypeError):
            ApprovalBackend()  # type: ignore[abstract]
