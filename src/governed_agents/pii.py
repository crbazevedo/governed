"""PII redaction utilities for event payloads.

This is the **single PII engine** for the governed-agents package.
Both ``PIIFilter`` handler and ``UXHandler`` delegate to ``redact_payload()``
so that field-name-based redaction, regex-based pattern matching, and
configurable extra patterns are applied consistently everywhere.

Design:
  - ``redact_payload`` returns a **new** dict; the original is never mutated.
  - Structured fields (known PII keys) get full value replacement.
  - Free-text fields get regex-based pattern matching from two sources:
      1. Built-in patterns (email, phone) always active.
      2. ``config.DEFAULT_PII_PATTERNS`` for SSN, CPF, credit card, etc.
  - Callers may pass ``extra_patterns`` for additional regex strings.
  - No external NLP libraries; pure regex.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from governed_agents.config import DEFAULT_PII_PATTERNS

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
# Built-in regex patterns for Tier 1 PII in free text
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

# Pre-compile DEFAULT_PII_PATTERNS from config
_CONFIG_PATTERNS: list[re.Pattern[str]] = [re.compile(p) for p in DEFAULT_PII_PATTERNS]


def _redact_string(
    value: str,
    extra_compiled: list[re.Pattern[str]] | None = None,
    redaction_marker: str = _FIELD_PLACEHOLDER,
) -> str:
    """Apply regex-based PII redaction to a free-text string."""
    result = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, value)
    result = _PHONE_RE.sub(_PHONE_PLACEHOLDER, result)
    # Apply config-level patterns (SSN, CPF, credit card, etc.)
    for pattern in _CONFIG_PATTERNS:
        result = pattern.sub(redaction_marker, result)
    # Apply any caller-supplied extra patterns
    if extra_compiled:
        for pattern in extra_compiled:
            result = pattern.sub(redaction_marker, result)
    return result


def _redact_value(
    key: str,
    value: Any,
    extra_compiled: list[re.Pattern[str]] | None = None,
    redaction_marker: str = _FIELD_PLACEHOLDER,
) -> Any:
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
        return {
            k: _redact_value(k, v, extra_compiled, redaction_marker)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_value(key, item, extra_compiled, redaction_marker)
            if not isinstance(item, str)
            else _redact_string(item, extra_compiled, redaction_marker)
            for item in value
        ]
    if isinstance(value, str):
        return _redact_string(value, extra_compiled, redaction_marker)

    # Non-string scalars (int, float, bool, None) pass through
    return value


def redact_payload(
    payload: dict[str, Any],
    *,
    extra_patterns: list[str] | None = None,
    redaction_marker: str = _FIELD_PLACEHOLDER,
) -> dict[str, Any]:
    """Return a deep copy of *payload* with Tier 1 PII scrubbed.

    This is the **single entry point** for PII redaction in the package.

    Redaction layers (applied in order):
      1. Known PII keys (``stakeholder``, ``email``, ``phone``, etc.) have their
         values replaced with ``[REDACTED]``.
      2. Built-in patterns: email addresses -> ``[EMAIL]``, phone numbers -> ``[PHONE]``.
      3. Config patterns (``config.DEFAULT_PII_PATTERNS``): SSN, CPF, credit card,
         passport, DOB, IP, etc. -> ``redaction_marker``.
      4. Extra patterns (caller-supplied) -> ``redaction_marker``.

    The original *payload* dict is **never** mutated.

    Args:
        payload: The event payload dict to redact.
        extra_patterns: Optional list of additional regex pattern strings.
        redaction_marker: String to replace config/extra pattern matches with.

    Returns:
        A new dict with PII redacted.
    """
    extra_compiled = [re.compile(p) for p in extra_patterns] if extra_patterns else None
    safe = copy.deepcopy(payload)
    return {
        k: _redact_value(k, v, extra_compiled, redaction_marker)
        for k, v in safe.items()
    }
