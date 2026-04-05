"""Human-in-the-loop (HITL) communication models.

Defines the intent types and message format for agent-to-human
communication in governed agent systems.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HITLIntent(str, Enum):
    """Intent types for human-in-the-loop messages."""

    INFORM = "inform"
    INPUT_REQUESTED = "input_requested"
    DECISION_REQUESTED = "decision_requested"
    ESCALATION = "escalation"


class HITLMessage(BaseModel):
    """A message from an agent to the system owner/operator.

    Carries intent, summary, detail body, decision options,
    timeout, and routing metadata.
    """

    intent: HITLIntent
    summary: str
    body: str = ""
    options: list[str] = Field(default_factory=list)
    vt_tier: int = Field(default=2, ge=0, le=4)
    agent_id: str = ""
    trace_id: str = ""
    timeout_seconds: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
