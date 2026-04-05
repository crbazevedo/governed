"""AuditLogger handler -- logs governance decisions to a pluggable backend.

# Layer: Persistent (interface-driven, zero built-in storage deps)

Accepts an AuditBackend implementation. Built-in LogAuditBackend uses
Python's logging module (zero deps, good for development). For production,
implement AuditBackend with file I/O, Redis streams, PostgreSQL,
OpenTelemetry, Datadog, or any audit infrastructure.

The audit handler should be marked as optional in the pipeline --
its failure should never block the governed action.
"""

from __future__ import annotations

import logging
import time

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.interfaces import AuditBackend, AuditEntry

logger = logging.getLogger(__name__)


class LogAuditBackend(AuditBackend):
    """Built-in audit backend using Python logging. Zero external deps.

    Logs each entry at INFO level to the ``governed_agents.audit`` logger.
    Also maintains an in-memory list for testing/inspection.

    For production, implement ``AuditBackend`` with your preferred storage.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._logger = logging.getLogger("governed_agents.audit")

    async def log(self, entry: AuditEntry) -> None:
        self._entries.append(entry)
        self._logger.info(
            "AUDIT action=%s agent=%s vt=%d verdict=%s handler=%s reason=%s",
            entry.action,
            entry.agent_id,
            entry.vt_tier,
            entry.verdict,
            entry.handler_name,
            entry.reason,
        )

    @property
    def entries(self) -> list[AuditEntry]:
        """All logged entries (for testing/inspection)."""
        return list(self._entries)


class AuditLogger(GovernanceHandler):
    """Logs governance decisions to a pluggable audit backend.

    Args:
        backend: AuditBackend implementation. Defaults to LogAuditBackend.
    """

    def __init__(self, backend: AuditBackend | None = None) -> None:
        self._backend = backend or LogAuditBackend()

    @property
    def name(self) -> str:
        return "audit_logger"

    @property
    def entries(self) -> list[AuditEntry]:
        """Access entries from the backend (if it supports inspection)."""
        if hasattr(self._backend, "entries"):
            return self._backend.entries  # type: ignore[attr-defined]
        return []

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        entry = AuditEntry(
            timestamp=time.time(),
            action=context.action,
            agent_id=context.agent_id,
            vt_tier=context.vt_tier,
            verdict="checked",
        )

        try:
            await self._backend.log(entry)
        except Exception:
            logger.warning(
                "AuditLogger: backend write failed (entry preserved if backend supports it)",
                exc_info=True,
            )

        return GovernanceResult.continue_(handler_name=self.name, reason="Audit logged")
