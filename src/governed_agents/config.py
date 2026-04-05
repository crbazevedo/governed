"""Default configuration for governed-agents.

Provides sensible defaults for all governance parameters.
Override at runtime by passing arguments to handler constructors.
"""

from __future__ import annotations

# ──────────────────────────────────────────────
# VT risk tiers — the core governance model
# ──────────────────────────────────────────────

VT_POLICIES: dict[int, dict[str, str]] = {
    0: {"action": "auto", "label": "Autonomous"},
    1: {"action": "log", "label": "Log & Proceed"},
    2: {"action": "approve", "label": "Require Approval"},
    3: {"action": "advise", "label": "Advise Only"},
    4: {"action": "block", "label": "Owner Only"},
}

# Maps VT tier int to policy keyword (for handler use)
VT_TIERS: dict[int, str] = {tier: policy["action"] for tier, policy in VT_POLICIES.items()}

DEFAULT_VT_TIER: int = 1

# ──────────────────────────────────────────────
# PII filter patterns (regex)
# ──────────────────────────────────────────────

DEFAULT_PII_PATTERNS: list[str] = [
    r"\b\d{3}-\d{2}-\d{4}\b",                                        # SSN (US)
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",                                # CPF (BR)
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",         # Email
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",                  # Credit card
    r"(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b",          # Phone (US)
    r"(?:\+55[\s.-]?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]\d{4}\b",      # Phone (BR)
    r"\b\d{2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b",                           # RG (BR)
    r"\b[A-Z]{1,2}\d{6,9}\b",                                        # Passport
    r"\b(?:0[1-9]|[12]\d|3[01])[/\-](?:0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b",  # DOB
    r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b",                # DOB ISO
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b",  # IPv4  # noqa: E501
    r"\b[0-3]\d{8}\b",                                                # US routing number
    r"(?i)(?:account|acct)[\s#:]*\d{8,17}\b",                        # US bank account
]

# ──────────────────────────────────────────────
# Payload limits
# ──────────────────────────────────────────────

MAX_PAYLOAD_SIZE_KB: int = 512

# ──────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────

RATE_LIMIT_MAX_CONCURRENT: int = 5
RATE_LIMIT_WINDOW_S: int = 60
