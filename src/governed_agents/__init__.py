"""governed-agents -- Governed autonomy middleware for AI agent systems.

Drop-in governance pipeline with VT (Verified Trust) risk tiers,
PII redaction, rate limiting, budget controls, and human-in-the-loop
escalation for any Python agent framework.
"""

from governed_agents.aow import AOWHandler, AOWState, AOWWindow
from governed_agents.approval import (
    ApprovalBackend,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
)
from governed_agents.decision_debt import (
    DebtState,
    DecisionDebt,
    DecisionDebtLedger,
)
from governed_agents.domain import (
    DomainBarrierHandler,
    DomainScope,
    GovernanceProfile,
)
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
    "AOWHandler",
    "AOWState",
    "AOWWindow",
    "ActionContext",
    "ApprovalBackend",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalStatus",
    "DebtState",
    "DecisionDebt",
    "DecisionDebtLedger",
    "DomainBarrierHandler",
    "DomainScope",
    "ExecutionMode",
    "GovernanceHandler",
    "GovernancePipeline",
    "GovernanceProfile",
    "GovernanceResult",
    "HITLIntent",
    "HITLMessage",
    "Verdict",
    "VTGovernanceHandler",
    "VTTier",
]
