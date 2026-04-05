"""PII detection and redaction — built-in regex implementation.

# Layer: Static (stateless, zero external dependencies)

Provides ``RegexPIIDetector``, the built-in implementation of the
``PIIDetector`` interface. Uses regex patterns for PII detection.
For production NLP-based detection, plug in Presidio, AWS Comprehend,
or Google DLP via the ``PIIDetector`` ABC in ``interfaces.py``.

The ``redact_payload()`` convenience function is preserved for backward
compatibility and for ``UXHandler``'s inline PII scrub.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from governed_agents.config import DEFAULT_PII_PATTERNS
from governed_agents.interfaces import PIIDetector, PIIMatch

# ──────────────────────────────────────────────
# Known PII field names (Tier 1 & Tier 2)
# Values in these keys are fully replaced.
# ──────────────────────────────────────────────
PII_FIELDS: frozenset[str] = frozenset(
    {
        "stakeholder",
        "stakeholders",
        "assigned_to",
        "owner",
        "email",
        "phone",
        "name",
    }
)

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
        return {k: _redact_value(k, v, extra_compiled, redaction_marker) for k, v in value.items()}
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
    return {k: _redact_value(k, v, extra_compiled, redaction_marker) for k, v in safe.items()}


# ──────────────────────────────────────────────
# RegexPIIDetector — built-in PIIDetector implementation
# ──────────────────────────────────────────────


class RegexPIIDetector(PIIDetector):
    """Built-in regex-based PII detector. Zero external dependencies.

    Good enough for demos, testing, and simple deployments. For production
    NLP-based detection, implement ``PIIDetector`` with Presidio, AWS
    Comprehend, Google DLP, or spaCy NER.

    Args:
        extra_patterns: Additional regex pattern strings to match.
        redaction_marker: String to replace matches with.
    """

    def __init__(
        self,
        extra_patterns: list[str] | None = None,
        redaction_marker: str = _FIELD_PLACEHOLDER,
    ) -> None:
        self._extra_patterns = extra_patterns
        self._redaction_marker = redaction_marker

    def scan(self, payload: dict[str, Any]) -> list[PIIMatch]:
        """Scan payload for PII. Returns list of matches."""
        original = payload
        redacted = redact_payload(
            original,
            extra_patterns=self._extra_patterns,
            redaction_marker=self._redaction_marker,
        )
        matches: list[PIIMatch] = []
        self._diff_payloads(original, redacted, "", matches)
        return matches

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a new payload with PII redacted."""
        return redact_payload(
            payload,
            extra_patterns=self._extra_patterns,
            redaction_marker=self._redaction_marker,
        )

    def _diff_payloads(
        self,
        original: Any,
        redacted: Any,
        path: str,
        matches: list[PIIMatch],
    ) -> None:
        """Recursively find differences between original and redacted payloads."""
        if isinstance(original, dict) and isinstance(redacted, dict):
            for key in original:
                self._diff_payloads(
                    original[key],
                    redacted.get(key),
                    f"{path}.{key}" if path else key,
                    matches,
                )
        elif isinstance(original, list) and isinstance(redacted, list):
            for i, (o, r) in enumerate(zip(original, redacted)):
                self._diff_payloads(o, r, f"{path}[{i}]", matches)
        elif original != redacted:
            matches.append(
                PIIMatch(
                    field_path=path,
                    pattern_name="regex",
                    original_value=str(original)[:50] if original else "",
                )
            )
