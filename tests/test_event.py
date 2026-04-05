"""Tests for GovernedEvent model."""

from __future__ import annotations

import uuid

from governed_agents.event import GovernedEvent


class TestGovernedEvent:
    def test_default_values(self):
        event = GovernedEvent(event_type="test")
        assert event.event_type == "test"
        assert event.vt_tier == 1
        assert event.source_agent == ""
        assert event.target_agent == ""
        assert event.domain == "general"
        assert event.payload == {}
        assert event.event_id  # Not empty
        assert event.timestamp  # Not empty

    def test_event_id_is_uuid(self):
        event = GovernedEvent(event_type="test")
        # Should be a valid UUID
        parsed = uuid.UUID(event.event_id)
        assert str(parsed) == event.event_id

    def test_timestamp_is_iso(self):
        event = GovernedEvent(event_type="test")
        # Should contain ISO format indicators
        assert "T" in event.timestamp

    def test_custom_values(self):
        event = GovernedEvent(
            event_type="tool_call",
            vt_tier=3,
            source_agent="orchestrator",
            target_agent="engineer",
            domain="engineering",
            payload={"tool": "deploy"},
        )
        assert event.vt_tier == 3
        assert event.source_agent == "orchestrator"
        assert event.domain == "engineering"
        assert event.payload["tool"] == "deploy"

    def test_serialization(self):
        event = GovernedEvent(
            event_type="agent_action",
            vt_tier=2,
            source_agent="pm",
        )
        data = event.model_dump()
        assert data["event_type"] == "agent_action"
        assert data["vt_tier"] == 2
        assert data["source_agent"] == "pm"
        assert "event_id" in data
        assert "timestamp" in data

    def test_deserialization(self):
        data = {
            "event_id": "abc-123",
            "event_type": "notification",
            "vt_tier": 0,
            "source_agent": "notifier",
            "domain": "ops",
            "payload": {"msg": "hello"},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        event = GovernedEvent(**data)
        assert event.event_id == "abc-123"
        assert event.event_type == "notification"
        assert event.payload["msg"] == "hello"

    def test_each_event_gets_unique_id(self):
        e1 = GovernedEvent(event_type="test")
        e2 = GovernedEvent(event_type="test")
        assert e1.event_id != e2.event_id

    def test_vt_tier_bounds(self):
        import pytest

        with pytest.raises(Exception):
            GovernedEvent(event_type="test", vt_tier=5)
        with pytest.raises(Exception):
            GovernedEvent(event_type="test", vt_tier=-1)
