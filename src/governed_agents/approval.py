"""Approval protocol -- interface for VT2+ human-in-the-loop approval.

# Layer: Static (interface definitions, no implementation)

The library defines the contract. Implementations (Redis, Slack, CLI, etc.)
are provided by the consuming application.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"
    TIMED_OUT = "timed_out"


@dataclass
class ApprovalRequest:
    """A request for human approval of a governed action."""

    trace_id: str
    action: str
    agent_id: str
    vt_tier: int
    summary: str
    body: str = ""
    options: list[str] | None = None
    timeout_seconds: int = 1800  # 30 min default
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalResponse:
    """Human response to an approval request."""

    trace_id: str
    status: ApprovalStatus
    responded_by: str = ""
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalBackend(ABC):
    """Abstract backend for handling approval requests.

    Implementations route approval requests to humans via
    different channels (Slack, CLI, web UI, etc.) and
    collect responses.
    """

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval request to the human."""
        ...

    @abstractmethod
    async def check_approval(self, trace_id: str) -> ApprovalResponse | None:
        """Check if an approval request has been responded to.

        Returns None if still pending.
        """
        ...

    @abstractmethod
    async def cancel_approval(self, trace_id: str) -> None:
        """Cancel a pending approval request."""
        ...
