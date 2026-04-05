"""governed-agents -- Governed autonomy middleware for AI agent systems.

Drop-in governance pipeline with VT (Verified Trust) risk tiers,
PII redaction, rate limiting, budget controls, and human-in-the-loop
escalation for any Python agent framework.
"""

from governed_agents.handler import (
    ActionContext,
    ExecutionMode,
    GovernanceHandler,
    GovernanceResult,
    Verdict,
)
from governed_agents.hitl import HITLIntent, HITLMessage
from governed_agents.pipeline import GovernancePipeline
from governed_agents.vt import VTGovernanceHandler, VTTier

__version__ = "0.1.0"

__all__ = [
    "ActionContext",
    "ExecutionMode",
    "GovernanceHandler",
    "GovernancePipeline",
    "GovernanceResult",
    "HITLIntent",
    "HITLMessage",
    "Verdict",
    "VTGovernanceHandler",
    "VTTier",
]
