"""Abstract interfaces for pluggable governance backends.

# Layer: Static (interface definitions, no implementation)

governed-agents implements governance DECISIONS (what to check, when to block).
Governance INFRASTRUCTURE (where to store, how to detect, what API to call) is
pluggable via these interfaces. Consumers provide implementations.

Design principle: the library should work with zero external dependencies.
Built-in defaults exist for demos and testing. Production systems plug in
their preferred backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────
# PII Detection
# ──────────────────────────────────────────────


@dataclass
class PIIMatch:
    """A detected PII occurrence."""

    field_path: str  # e.g., "payload.contact.email"
    pattern_name: str  # e.g., "email", "ssn", "cpf"
    original_value: str = ""  # The matched text (for logging, not for storage)
    start: int = 0
    end: int = 0


class PIIDetector(ABC):
    """Interface for PII detection backends.

    Built-in: RegexPIIDetector (pattern-based, zero deps).
    Production: Presidio, AWS Comprehend, Google DLP, spaCy NER.
    """

    @abstractmethod
    def scan(self, payload: dict[str, Any]) -> list[PIIMatch]:
        """Scan a payload dict for PII. Returns list of matches."""
        ...

    @abstractmethod
    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a new payload dict with PII redacted."""
        ...


# ──────────────────────────────────────────────
# Rate Limiting
# ──────────────────────────────────────────────


class RateLimitPolicy(ABC):
    """Interface for rate limit evaluation.

    Built-in: InMemoryRateLimit (sliding window, single-process).
    Production: Redis-based, API gateway, litellm rate limits.
    """

    @abstractmethod
    async def check(self, agent_id: str, action: str) -> bool:
        """Return True if action is within rate limits, False if exceeded."""
        ...

    @abstractmethod
    async def record(self, agent_id: str, action: str) -> None:
        """Record that an action was taken (for window tracking)."""
        ...


# ──────────────────────────────────────────────
# Cost Tracking
# ──────────────────────────────────────────────


class CostProvider(ABC):
    """Interface for retrieving current cumulative cost.

    Built-in: ManualCostTracker (add_cost() calls).
    Production: litellm callbacks, LangSmith, Helicone, custom.
    """

    @abstractmethod
    def current_cost(self, agent_id: str | None = None) -> float:
        """Return current cumulative cost in USD.

        If agent_id is provided, return cost for that agent only.
        If None, return total cost across all agents.
        """
        ...


# ──────────────────────────────────────────────
# Audit Logging
# ──────────────────────────────────────────────


@dataclass
class AuditEntry:
    """Structured audit log entry."""

    timestamp: float
    action: str
    agent_id: str
    vt_tier: int
    verdict: str  # "allow", "block", "modify"
    handler_name: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditBackend(ABC):
    """Interface for audit log storage.

    Built-in: LogAuditBackend (Python logging, zero deps).
    Production: file, Redis streams, PostgreSQL, OpenTelemetry, Datadog.
    """

    @abstractmethod
    async def log(self, entry: AuditEntry) -> None:
        """Persist an audit entry."""
        ...


# ──────────────────────────────────────────────
# Persistence (Decision Debt, AOW)
# ──────────────────────────────────────────────


class DebtStore(ABC):
    """Interface for persisting DecisionDebt state across restarts.

    Built-in: InMemoryDebtStore (DecisionDebtLedger, no persistence).
    Production: Redis, PostgreSQL, SQLite.
    """

    @abstractmethod
    async def save(self, debt_id: str, data: dict[str, Any]) -> None:
        """Persist a decision debt record."""
        ...

    @abstractmethod
    async def load(self, debt_id: str) -> dict[str, Any] | None:
        """Load a decision debt record. Returns None if not found."""
        ...

    @abstractmethod
    async def list_pending(self) -> list[dict[str, Any]]:
        """List all unresolved debt records."""
        ...


class AOWStore(ABC):
    """Interface for persisting AOW window state.

    Built-in: In-memory (AOWWindow dataclass, no persistence).
    Production: Redis, database.
    """

    @abstractmethod
    async def save(self, action_id: str, data: dict[str, Any]) -> None:
        """Persist an AOW window state."""
        ...

    @abstractmethod
    async def load(self, action_id: str) -> dict[str, Any] | None:
        """Load an AOW window state. Returns None if not found."""
        ...
