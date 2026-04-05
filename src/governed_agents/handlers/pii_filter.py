"""PIIFilter handler -- detects and redacts PII patterns in payloads."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from governed_agents.config import DEFAULT_PII_PATTERNS
from governed_agents.handler import (
    CallbackContext,
    CallbackHandler,
    CallbackResult,
)

logger = logging.getLogger(__name__)


class PIIFilter(CallbackHandler):
    """Checks for PII patterns in outbound payloads.

    Scans all string values in the payload dict for PII patterns
    (SSN, CPF, email, credit card, phone). If PII is found, returns MODIFY
    with the PII redacted, or ABORT if redaction is disabled.

    Attributes:
        patterns: List of compiled regex patterns to check.
        redact: If True, redact PII and continue. If False, abort on PII.
        redaction_marker: String to replace PII matches with.
    """

    def __init__(
        self,
        patterns: list[str] | None = None,
        redact: bool = True,
        redaction_marker: str = "[REDACTED]",
    ) -> None:
        self._patterns = [re.compile(p) for p in (patterns or DEFAULT_PII_PATTERNS)]
        self._redact = redact
        self._redaction_marker = redaction_marker

    @property
    def name(self) -> str:
        return "pii_filter"

    async def check(self, context: CallbackContext) -> CallbackResult:
        pii_found = False
        if self._redact:
            new_payload = deepcopy(context.payload)
            pii_found = self._scan_and_redact(new_payload)
            if pii_found:
                new_context = CallbackContext(
                    action=context.action,
                    agent_id=context.agent_id,
                    vt_tier=context.vt_tier,
                    payload=new_payload,
                    metadata=dict(context.metadata),
                )
                logger.warning("PIIFilter: PII detected and redacted in payload")
                return CallbackResult.modify(
                    modified_context=new_context,
                    handler_name=self.name,
                    reason="PII detected and redacted",
                )
        else:
            pii_found = self._scan_payload(context.payload)
            if pii_found:
                return CallbackResult.abort(
                    handler_name=self.name,
                    reason="PII detected in payload (redaction disabled)",
                )

        return CallbackResult.continue_(handler_name=self.name)

    def _scan_payload(self, payload: dict[str, Any]) -> bool:
        """Recursively scan payload for PII patterns. Returns True if found."""
        for value in payload.values():
            if isinstance(value, str):
                for pattern in self._patterns:
                    if pattern.search(value):
                        return True
            elif isinstance(value, dict):
                if self._scan_payload(value):
                    return True
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        for pattern in self._patterns:
                            if pattern.search(item):
                                return True
                    elif isinstance(item, dict):
                        if self._scan_payload(item):
                            return True
        return False

    def _scan_and_redact(self, payload: dict[str, Any]) -> bool:
        """Recursively scan and redact PII in payload. Returns True if PII was found."""
        found = False
        for key, value in payload.items():
            if isinstance(value, str):
                for pattern in self._patterns:
                    new_value, count = pattern.subn(self._redaction_marker, value)
                    if count > 0:
                        payload[key] = new_value
                        value = new_value
                        found = True
            elif isinstance(value, dict):
                if self._scan_and_redact(value):
                    found = True
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        for pattern in self._patterns:
                            new_item, count = pattern.subn(self._redaction_marker, item)
                            if count > 0:
                                value[i] = new_item
                                item = new_item
                                found = True
                    elif isinstance(item, dict):
                        if self._scan_and_redact(item):
                            found = True
        return found
