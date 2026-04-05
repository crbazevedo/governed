"""PIIFilter handler -- detects and redacts PII in payloads.

# Layer: Static (stateless governance handler)

Accepts a pluggable PIIDetector backend. Built-in RegexPIIDetector
is used by default (zero external deps). For production, plug in
Presidio, AWS Comprehend, Google DLP, or any PIIDetector implementation.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.interfaces import PIIDetector
from governed_agents.pii import RegexPIIDetector

logger = logging.getLogger(__name__)


class PIIFilter(GovernanceHandler):
    """Checks for PII in outbound payloads using a pluggable detector.

    Args:
        detector: PIIDetector implementation. Defaults to RegexPIIDetector.
        redact: If True, redact PII and continue. If False, block on PII.
    """

    def __init__(
        self,
        detector: PIIDetector | None = None,
        redact: bool = True,
        # Convenience: extra regex patterns forwarded to default detector
        patterns: list[str] | None = None,
        redaction_marker: str = "[REDACTED]",
    ) -> None:
        if detector is not None:
            self._detector = detector
        else:
            self._detector = RegexPIIDetector(
                extra_patterns=patterns,
                redaction_marker=redaction_marker,
            )
        self._redact = redact

    @property
    def name(self) -> str:
        return "pii_filter"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        matches = self._detector.scan(context.payload)

        if not matches:
            return GovernanceResult.continue_(handler_name=self.name)

        if not self._redact:
            affected_fields = list({m.field_path for m in matches})
            return GovernanceResult.abort(
                handler_name=self.name,
                reason=f"PII detected in payload ({len(matches)} matches, redaction disabled)",
                suggestion="Remove PII from the payload before retrying",
                alternatives=[f"Remove PII from field: {field}" for field in affected_fields],
            )

        redacted_payload = self._detector.redact(context.payload)
        new_context = replace(context, payload=redacted_payload)
        logger.warning("PIIFilter: %d PII matches detected and redacted", len(matches))
        return GovernanceResult.modify(
            modified_context=new_context,
            handler_name=self.name,
            reason=f"PII detected and redacted ({len(matches)} matches)",
        )
