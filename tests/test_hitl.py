"""Tests for HITL communication models."""

from __future__ import annotations

from governed_agents.hitl import HITLIntent, HITLMessage


class TestHITLIntent:
    def test_values(self):
        assert HITLIntent.INFORM == "inform"
        assert HITLIntent.INPUT_REQUESTED == "input_requested"
        assert HITLIntent.DECISION_REQUESTED == "decision_requested"
        assert HITLIntent.ESCALATION == "escalation"

    def test_enum_is_str(self):
        assert isinstance(HITLIntent.INFORM, str)


class TestHITLMessage:
    def test_basic_creation(self):
        msg = HITLMessage(
            intent=HITLIntent.INFORM,
            summary="Task complete",
        )
        assert msg.intent == HITLIntent.INFORM
        assert msg.summary == "Task complete"
        assert msg.body == ""
        assert msg.options == []
        assert msg.vt_tier == 2
        assert msg.agent_id == ""
        assert msg.trace_id == ""
        assert msg.timeout_seconds is None

    def test_full_creation(self):
        msg = HITLMessage(
            intent=HITLIntent.DECISION_REQUESTED,
            summary="Approve deployment?",
            body="Deploy v2.0 to production.",
            options=["Approve", "Deny", "Defer"],
            vt_tier=2,
            agent_id="deployer",
            trace_id="tr-abc123",
            timeout_seconds=1800,
            metadata={"deployment_id": "d-123"},
        )
        assert msg.options == ["Approve", "Deny", "Defer"]
        assert msg.timeout_seconds == 1800
        assert msg.metadata["deployment_id"] == "d-123"

    def test_serialization(self):
        msg = HITLMessage(
            intent=HITLIntent.ESCALATION,
            summary="Critical issue",
            vt_tier=4,
        )
        data = msg.model_dump()
        assert data["intent"] == "escalation"
        assert data["summary"] == "Critical issue"
        assert data["vt_tier"] == 4

    def test_deserialization(self):
        data = {
            "intent": "input_requested",
            "summary": "Need input",
            "body": "Please confirm.",
            "options": ["Yes", "No"],
            "vt_tier": 2,
            "agent_id": "bot",
            "trace_id": "tr-xyz",
        }
        msg = HITLMessage(**data)
        assert msg.intent == HITLIntent.INPUT_REQUESTED
        assert msg.agent_id == "bot"

    def test_vt_tier_validation(self):
        import pytest
        with pytest.raises(Exception):
            HITLMessage(intent=HITLIntent.INFORM, summary="Bad", vt_tier=5)
        with pytest.raises(Exception):
            HITLMessage(intent=HITLIntent.INFORM, summary="Bad", vt_tier=-1)
