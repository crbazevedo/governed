"""governed-agents -- Governed autonomy middleware for AI agent systems.

Drop-in governance pipeline with VT (Verified Trust) risk tiers,
PII redaction, rate limiting, budget controls, and human-in-the-loop
escalation for any Python agent framework.

Core types are exported here. Advanced features via submodule imports:

    from governed_agents.aow import AOWWindow, AOWHandler, AOWState
    from governed_agents.decision_debt import DecisionDebt, DecisionDebtLedger, DebtState
    from governed_agents.approval import ApprovalBackend, ApprovalRequest, ApprovalResponse
    from governed_agents.domain import GovernanceProfile, DomainBarrierHandler, DomainScope
    from governed_agents.handlers import PIIFilter, RateLimiter, BudgetGatekeeper, AuditLogger
    from governed_agents.decorator import governed, configure, GovernanceError
    from governed_agents.profile_loader import load_profile, load_pipeline_config
"""

from governed_agents.handler import (
    ActionContext,
    ExecutionMode,
    GovernanceHandler,
    GovernanceResult,
    Verdict,
)
from governed_agents.hitl import HITLIntent, HITLMessage
from governed_agents.pipeline import ExecutionTrace, GovernancePipeline, HandlerTrace
from governed_agents.vt import VTGovernanceHandler, VTTier

__version__ = "0.1.0"

__all__ = [
    "ActionContext",
    "ExecutionMode",
    "ExecutionTrace",
    "GovernanceHandler",
    "GovernancePipeline",
    "GovernanceResult",
    "HandlerTrace",
    "HITLIntent",
    "HITLMessage",
    "Verdict",
    "VTGovernanceHandler",
    "VTTier",
]
