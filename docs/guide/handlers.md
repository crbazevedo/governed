# Handlers

Built-in handlers provide common governance capabilities with pluggable backends. Every handler uses a default zero-dependency implementation for development and accepts production backends via constructor injection.

## Overview

| Handler | Layer | Default Backend | Pluggable Interface | Purpose |
|---------|-------|----------------|-------------------|---------|
| `PIIFilter` | Static | `RegexPIIDetector` | `PIIDetector` | Detect/redact PII in payloads |
| `RateLimiter` | Dynamic | `InMemoryRateLimit` | `RateLimitPolicy` | Enforce action frequency limits |
| `BudgetGatekeeper` | Dynamic | `ManualCostTracker` | `CostProvider` | Enforce cumulative cost limits |
| `AuditLogger` | Persistent | `LogAuditBackend` | `AuditBackend` | Log governance decisions |
| `ComplianceChecker` | Static | -- | -- | Payload size, VT consistency checks |
| `UXHandler` | Static | -- | -- | Format VT2+ actions as HITL messages |

All handlers are importable from `governed_agents.handlers`:

```python
from governed_agents.handlers import (
    PIIFilter,
    RateLimiter,
    BudgetGatekeeper,
    AuditLogger,
    ComplianceChecker,
    UXHandler,
)
```

---

## PIIFilter

Detects and redacts PII in action payloads. Default mode: redact and continue (MODIFY). Block mode: reject payloads containing PII (BLOCK).

```python
# Default: redact PII and continue
pipeline.add(PIIFilter())

# Block mode: reject payloads with PII
pipeline.add(PIIFilter(redact=False))

# Custom patterns
pipeline.add(PIIFilter(patterns=[r"\bINTERNAL-\d{6}\b"]))

# Custom redaction marker
pipeline.add(PIIFilter(redaction_marker="***"))
```

**Default patterns detected:** SSN (US), CPF (BR), email, credit card, phone (US/BR), RG (BR), passport, date of birth, IPv4, routing number, bank account.

**Pluggable backend:** Pass any `PIIDetector` implementation:

```python
from governed_agents.interfaces import PIIDetector

pipeline.add(PIIFilter(detector=PresidioPIIDetector()))
```

See [Custom Backends](custom-backends.md) for implementing `PIIDetector`.

---

## RateLimiter

Enforces action frequency limits using a sliding window.

```python
# 10 actions per 60-second window (default)
pipeline.add(RateLimiter(max_per_window=10, window_seconds=60))
```

When the limit is exceeded, the handler blocks with a recovery plan:

- **Suggestion:** "Wait 12s before retrying"
- **Recovery:** `RETRY_AFTER_DELAY` with `delay_seconds` in context

**Pluggable backend:** Pass any `RateLimitPolicy` implementation:

```python
from governed_agents.interfaces import RateLimitPolicy

pipeline.add(RateLimiter(policy=RedisRateLimitPolicy(redis_client)))
```

---

## BudgetGatekeeper

Enforces cumulative cost limits. Blocks when total spend exceeds the budget.

```python
gatekeeper = BudgetGatekeeper(budget_limit_usd=5.0)
pipeline.add(gatekeeper)

# Record costs after each LLM call
gatekeeper.add_cost(0.03)
gatekeeper.add_cost(0.12, agent_id="analyst")
```

When the budget is exceeded:

- **Suggestion:** "Reduce cost by using a cheaper model or smaller context"
- **Recovery:** `USE_CHEAPER_RESOURCE`, `BATCH_WITH_OTHERS`, `DELEGATE_TO_HUMAN`

**Pluggable backend:** Pass any `CostProvider` implementation:

```python
from governed_agents.interfaces import CostProvider

gatekeeper = BudgetGatekeeper(
    budget_limit_usd=10.0,
    cost_provider=LitellmCostProvider(),
)
```

!!! tip "ManualCostTracker"
    The default `ManualCostTracker` requires you to call `add_cost()` after each action. For automatic tracking, implement `CostProvider` with litellm or your billing system.

---

## AuditLogger

Logs governance decisions to a pluggable backend. Should be marked `optional=True` -- audit failures must never block governed actions.

```python
pipeline.add(AuditLogger(), optional=True)
```

The default `LogAuditBackend` logs to Python's `logging` module and maintains an in-memory list for testing:

```python
audit = AuditLogger()
pipeline.add(audit, optional=True)

# After pipeline execution
for entry in audit.entries:
    print(f"{entry.action} -> {entry.verdict} (VT{entry.vt_tier})")
```

**Pluggable backend:** Pass any `AuditBackend` implementation:

```python
from governed_agents.interfaces import AuditBackend

pipeline.add(AuditLogger(backend=FileAuditBackend("audit.jsonl")))
```

---

## ComplianceChecker

Validates payload size, audit readiness, and VT tier consistency.

```python
# Strict mode: block on violations (default)
pipeline.add(ComplianceChecker())

# Non-strict mode: warn but continue
pipeline.add(ComplianceChecker(strict_mode=False))

# Custom payload size limit
pipeline.add(ComplianceChecker(max_payload_kb=256))
```

Checks performed:

1. **Payload size:** Rejects payloads exceeding `max_payload_kb` (default: 512 KB).
2. **Audit readiness:** VT1+ actions must have `agent_id` and `action` set.
3. **VT consistency:** If `metadata["governance_vt_tier"]` is set, it must match `context.vt_tier`.

---

## UXHandler

Formats VT2+ actions as human-in-the-loop (HITL) messages. Runs **before** `VTGovernanceHandler` to prepare the formatted request.

```python
pipeline.add(UXHandler())          # Formats HITL messages
pipeline.add(VTGovernanceHandler()) # Then enforces VT tier
```

For VT0-1 actions, the handler passes through. For VT2+, it creates an `HITLMessage` in `context.metadata["hitl_message"]` with:

- Summary and body text (PII-scrubbed)
- Approval options ("Approve"/"Deny" for VT2)
- Timeout (30 minutes for VT2)
- Trace ID for correlation

The formatted message is available for downstream handlers or your approval routing system.

---

## Handler Execution Order

A typical pipeline orders handlers from most restrictive to least:

```python
pipeline = GovernancePipeline()
pipeline.add(PIIFilter())              # 1. Redact PII first
pipeline.add(RateLimiter())            # 2. Check frequency
pipeline.add(BudgetGatekeeper())       # 3. Check budget
pipeline.add(ComplianceChecker())      # 4. Validate compliance
pipeline.add(UXHandler())              # 5. Format HITL messages
pipeline.add(VTGovernanceHandler())    # 6. Enforce VT tier
pipeline.add(AuditLogger(), optional=True)  # 7. Log (optional)
```

PII redaction should happen before any handler that might log or display the payload. Audit logging should be last and optional.
