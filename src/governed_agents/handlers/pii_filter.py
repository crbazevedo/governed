"""PIIFilter handler -- detects and redacts PII patterns in payloads.

Delegates all PII scanning and redaction to the centralized ``pii`` module
so that field-name-based and regex-based redaction are consistent across
PIIFilter and UXHandler.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.pii import redact_payload

logger = logging.getLogger(__name__)


class PIIFilter(GovernanceHandler):
    """Checks for PII patterns in outbound payloads.

    Scans all string values in the payload dict for PII patterns
    (SSN, CPF, email, credit card, phone) using the centralized pii module.
    If PII is found, returns MODIFY with the PII redacted, or BLOCK if
    redaction is disabled.

    Attributes:
        patterns: Optional list of additional regex pattern strings.
        redact: If True, redact PII and continue. If False, block on PII.
        redaction_marker: String to replace PII matches with.
    """

    def __init__(
        self,
        patterns: list[str] | None = None,
        redact: bool = True,
        redaction_marker: str = "[REDACTED]",
    ) -> None:
        self._extra_patterns = patterns
        self._redact = redact
        self._redaction_marker = redaction_marker

    @property
    def name(self) -> str:
        return "pii_filter"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        original_payload = context.payload
        redacted_payload = redact_payload(
            original_payload,
            extra_patterns=self._extra_patterns,
            redaction_marker=self._redaction_marker,
        )

        pii_found = redacted_payload != original_payload

        if not pii_found:
            return GovernanceResult.continue_(handler_name=self.name)

        if not self._redact:
            return GovernanceResult.abort(
                handler_name=self.name,
                reason="PII detected in payload (redaction disabled)",
            )

        new_context = ActionContext(
            action=context.action,
            agent_id=context.agent_id,
            vt_tier=context.vt_tier,
            payload=redacted_payload,
            metadata=dict(context.metadata),
        )
        logger.warning("PIIFilter: PII detected and redacted in payload")
        return GovernanceResult.modify(
            modified_context=new_context,
            handler_name=self.name,
            reason="PII detected and redacted",
        )
