"""Framework-agnostic governed event model.

Provides a standard event structure for governed agent systems,
carrying VT tier, routing, and payload information.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _default_event_id() -> str:
    return str(uuid.uuid4())


def _default_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernedEvent(BaseModel):
    """A governed event carrying action metadata through the system.

    Framework-agnostic: works with any agent framework (Pydantic AI,
    LangGraph, CrewAI, Google ADK, or custom).

    Attributes:
        event_id: Unique identifier (auto-generated UUID).
        event_type: Type of event (e.g., "tool_call", "agent_action").
        vt_tier: VT risk tier (0-4).
        source_agent: Agent that generated this event.
        target_agent: Intended recipient agent (empty for broadcast).
        domain: Business domain (e.g., "finance", "engineering").
        payload: Extensible event data.
        timestamp: ISO 8601 timestamp (auto-generated).
    """

    event_id: str = Field(default_factory=_default_event_id)
    event_type: str
    vt_tier: int = Field(default=1, ge=0, le=4)
    source_agent: str = ""
    target_agent: str = ""
    domain: str = "general"
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_default_timestamp)
