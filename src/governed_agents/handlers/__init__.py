"""Built-in governance pipeline handlers.

Each handler uses a pluggable backend via the interfaces in ``interfaces.py``.
Built-in defaults require zero external deps. Swap in production backends
(Presidio, Redis, litellm, etc.) via constructor injection.

Handlers:
- PIIFilter: detect/redact PII (default: RegexPIIDetector; plug in Presidio)
- RateLimiter: enforce action frequency (default: InMemoryRateLimit; plug in Redis)
- BudgetGatekeeper: enforce cost limits (default: ManualCostTracker; plug in litellm)
- AuditLogger: log decisions (default: LogAuditBackend; plug in file/Redis/SIEM)
- ComplianceChecker: validate payload size, VT consistency
- UXHandler: format VT2+ actions as HITL messages
"""

from governed_agents.handlers.audit import AuditLogger
from governed_agents.handlers.budget import BudgetGatekeeper
from governed_agents.handlers.compliance import ComplianceChecker
from governed_agents.handlers.pii_filter import PIIFilter
from governed_agents.handlers.rate_limiter import RateLimiter
from governed_agents.handlers.ux import UXHandler

__all__ = [
    "AuditLogger",
    "BudgetGatekeeper",
    "ComplianceChecker",
    "PIIFilter",
    "RateLimiter",
    "UXHandler",
]
