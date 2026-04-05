"""PII redaction utilities for event payloads.

Strips Tier 1 PII from payloads before they reach external systems,
audit logs, or human-facing messages. Redaction is applied at the event
emission boundary so individual tools never need to worry about it.

Design:
  - ``redact_payload`` returns a **new** dict; the original is never mutated.
  - Structured fields (known PII keys) get full value replacement.
  - Free-text fields get regex-based pattern matching.
  - All regex patterns target Tier 1 identifiers:
    emails, phone numbers, and potentially sensitive named fields.
  - No external NLP libraries; pure regex.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# ──────────────────────────────────────────────
# Known PII field names (Tier 1 & Tier 2)
# Values in these keys are fully replaced.
# ──────────────────────────────────────────────
PII_FIELDS: frozenset[str] = frozenset({
    "stakeholder",
    "stakeholders",
    "assigned_to",
    "owner",
    "email",
    "phone",
    "name",
})

# ──────────────────────────────────────────────
# Regex patterns for Tier 1 PII in free text
# ──────────────────────────────────────────────

# Email: word-chars, dots, hyphens, plus-signs @ domain
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Phone: international and North American formats
_PHONE_RE = re.compile(
    r"(?<![a-zA-Z0-9\-])"
    r"(?:"
    r"\(\d{3,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|"
    r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,4}"
    r"|"
    r"\d{3}[\-\.]\d{3}[\-\.]\d{4}"
    r")"
    r"(?![a-zA-Z0-9\-])",
)

# Placeholder tokens
_EMAIL_PLACEHOLDER = "[EMAIL]"
_PHONE_PLACEHOLDER = "[PHONE]"
_FIELD_PLACEHOLDER = "[REDACTED]"


def _redact_string(value: str) -> str:
    """Apply regex-based PII redaction to a free-text string."""
    result = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, value)
    result = _PHONE_RE.sub(_PHONE_PLACEHOLDER, result)
    return result


def _redact_value(key: str, value: Any) -> Any:
    """Redact a single key/value pair.

    - If the key is a known PII field, replace the entire value.
    - If the value is a string, apply regex scrubbing.
    - If the value is a list, recurse over elements.
    - If the value is a dict, recurse over key/value pairs.
    """
    lower_key = key.lower()

    # Known PII field: full replacement
    if lower_key in PII_FIELDS:
        if isinstance(value, list):
            return [_FIELD_PLACEHOLDER] * len(value)
        return _FIELD_PLACEHOLDER

    # Recurse into nested structures
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [
            _redact_value(key, item) if not isinstance(item, str)
            else _redact_string(item)
            for item in value
        ]
    if isinstance(value, str):
        return _redact_string(value)

    # Non-string scalars (int, float, bool, None) pass through
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *payload* with Tier 1 PII scrubbed.

    - Known PII keys (``stakeholder``, ``email``, ``phone``, etc.) have their
      values replaced with ``[REDACTED]``.
    - Free-text string values are scanned for email and phone patterns which
      are replaced with ``[EMAIL]`` and ``[PHONE]`` respectively.
    - The original *payload* dict is **never** mutated.

    Args:
        payload: The event payload dict to redact.

    Returns:
        A new dict with PII redacted.
    """
    safe = copy.deepcopy(payload)
    return {k: _redact_value(k, v) for k, v in safe.items()}
