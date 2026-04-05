"""governed-agents -- Governed autonomy middleware for AI agent systems.

Drop-in governance pipeline with VT (Verified Trust) risk tiers,
PII redaction, rate limiting, budget controls, and human-in-the-loop
escalation for any Python agent framework.
"""

from governed_agents.event import GovernedEvent
from governed_agents.handler import (
    CallbackContext,
    CallbackHandler,
    CallbackResult,
    ExecutionMode,
    HandlerRegistration,
    ResultAction,
)
from governed_agents.hitl import HITLIntent, HITLMessage
from governed_agents.pipeline import CallbackPipeline
from governed_agents.vt import VTGovernanceHandler, VTPolicy, VTTier

__version__ = "0.1.0"

__all__ = [
    "CallbackContext",
    "CallbackHandler",
    "CallbackPipeline",
    "CallbackResult",
    "ExecutionMode",
    "GovernedEvent",
    "HandlerRegistration",
    "HITLIntent",
    "HITLMessage",
    "ResultAction",
    "VTGovernanceHandler",
    "VTPolicy",
    "VTTier",
]
