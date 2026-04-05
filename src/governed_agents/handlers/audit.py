"""AuditLogger handler -- logs all actions to a JSON file or Redis stream."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from governed_agents.handler import (
    CallbackContext,
    CallbackHandler,
    CallbackResult,
)

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """Structured audit log entry."""

    timestamp: float
    action: str
    agent_id: str
    vt_tier: int
    result: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogger(CallbackHandler):
    """Logs all actions to an audit trail.

    Supports two backends:
    - "json": Appends JSON lines to a local file (default).
    - "redis": Writes to a Redis Stream (requires [redis] extra).

    Falls back to in-memory-only logging if the backend is unavailable
    (graceful degradation). The in-memory list is always populated
    regardless of backend availability.

    The audit logger should be marked as optional in the pipeline --
    its failure should never block the action being audited.

    Args:
        backend: "json" or "redis".
        path: File path for JSON backend. Defaults to "audit.jsonl".
        redis_url: Redis URL for Redis backend. Defaults to "redis://localhost:6379/0".
        stream_name: Redis stream name. Defaults to "governed:audit:log".
    """

    def __init__(
        self,
        backend: str = "json",
        path: str = "audit.jsonl",
        redis_url: str = "redis://localhost:6379/0",
        stream_name: str = "governed:audit:log",
    ) -> None:
        self._backend = backend
        self._path = Path(path)
        self._redis_url = redis_url
        self._stream_name = stream_name
        self._entries: list[AuditEntry] = []
        self._redis: Any | None = None
        self._redis_available: bool | None = None

    @property
    def name(self) -> str:
        return "audit_logger"

    @property
    def entries(self) -> list[AuditEntry]:
        """Return all audit entries (for testing/inspection)."""
        return list(self._entries)

    async def check(self, context: CallbackContext) -> CallbackResult:
        entry = AuditEntry(
            timestamp=time.time(),
            action=context.action,
            agent_id=context.agent_id,
            vt_tier=context.vt_tier,
            result="checked",
            metadata=dict(context.metadata),
        )
        self._entries.append(entry)

        if self._backend == "json":
            self._write_json(entry)
        elif self._backend == "redis":
            self._write_redis(entry)

        logger.debug(
            "AuditLogger: action='%s' agent='%s' vt=%d",
            context.action,
            context.agent_id,
            context.vt_tier,
        )
        return CallbackResult.continue_(handler_name=self.name, reason="Audit logged")

    def _write_json(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSON lines file."""
        try:
            record = {
                "timestamp": entry.timestamp,
                "action": entry.action,
                "agent_id": entry.agent_id,
                "vt_tier": entry.vt_tier,
                "result": entry.result,
                "metadata": entry.metadata,
            }
            with open(self._path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            logger.warning(
                "AuditLogger: failed to write to %s -- entry preserved in-memory",
                self._path,
                exc_info=True,
            )

    def _get_redis(self) -> Any | None:
        """Lazy Redis connection with graceful degradation."""
        if self._redis_available is False:
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis as redis_lib

            r = redis_lib.Redis.from_url(
                self._redis_url, decode_responses=True, socket_connect_timeout=2
            )
            r.ping()
            self._redis = r
            self._redis_available = True
            return r
        except Exception:
            self._redis_available = False
            logger.warning(
                "AuditLogger: Redis unavailable -- falling back to in-memory only",
                exc_info=True,
            )
            return None

    def _write_redis(self, entry: AuditEntry) -> None:
        """Write an audit entry to the Redis stream."""
        r = self._get_redis()
        if r is None:
            return
        try:
            audit_fields: dict[str, str] = {
                "timestamp": str(entry.timestamp),
                "action": entry.action,
                "agent_id": entry.agent_id,
                "vt_tier": str(entry.vt_tier),
                "result": entry.result,
                "metadata": json.dumps(entry.metadata),
            }
            r.xadd(self._stream_name, audit_fields)
        except Exception:
            logger.warning(
                "AuditLogger: failed to write to Redis stream -- entry preserved in-memory",
                exc_info=True,
            )
            self._redis_available = False
            self._redis = None
