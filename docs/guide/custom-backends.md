# Custom Backends

`governed-agents` implements governance *decisions* (what to check, when to block). Governance *infrastructure* (where to store, how to detect, what API to call) is pluggable via abstract interfaces. You provide the implementation.

This is the interface-first philosophy: the library works with zero external dependencies using built-in defaults. Swap in production backends without changing any governance logic.

## Available Interfaces

| Interface | Purpose | Built-in Default |
|-----------|---------|-----------------|
| `PIIDetector` | Detect/redact PII in payloads | `RegexPIIDetector` |
| `RateLimitPolicy` | Evaluate action frequency | `InMemoryRateLimit` |
| `CostProvider` | Retrieve current cumulative cost | `ManualCostTracker` |
| `AuditBackend` | Persist governance decisions | `LogAuditBackend` |
| `ApprovalBackend` | Route approval requests to humans | None (you must implement) |
| `DebtStore` | Persist DecisionDebt state | In-memory (DecisionDebtLedger) |
| `AOWStore` | Persist AOW window state | In-memory (AOWWindow) |

All interfaces are in `governed_agents.interfaces` except `ApprovalBackend` (in `governed_agents.approval`).

---

## Implementing PIIDetector (Presidio Example)

The `PIIDetector` interface has two methods: `scan()` and `redact()`.

```python
from governed_agents.interfaces import PIIDetector, PIIMatch
from typing import Any

class PresidioPIIDetector(PIIDetector):
    """PII detection using Microsoft Presidio."""

    def __init__(self, language: str = "en"):
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        self._analyzer = AnalyzerEngine()
        self._anonymizer = AnonymizerEngine()
        self._language = language

    def scan(self, payload: dict[str, Any]) -> list[PIIMatch]:
        matches = []
        for key, value in payload.items():
            if not isinstance(value, str):
                continue
            results = self._analyzer.analyze(
                text=value, language=self._language
            )
            for r in results:
                matches.append(PIIMatch(
                    field_path=f"payload.{key}",
                    pattern_name=r.entity_type.lower(),
                    original_value=value[r.start:r.end],
                    start=r.start,
                    end=r.end,
                ))
        return matches

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(payload)
        for key, value in redacted.items():
            if not isinstance(value, str):
                continue
            results = self._analyzer.analyze(
                text=value, language=self._language
            )
            if results:
                result = self._anonymizer.anonymize(text=value, analyzer_results=results)
                redacted[key] = result.text
        return redacted
```

Use it:

```python
from governed_agents.handlers import PIIFilter

pipeline.add(PIIFilter(detector=PresidioPIIDetector()))
```

!!! tip
    Install the presidio extra: `pip install governed-agents[presidio]`

---

## Implementing CostProvider (litellm Example)

The `CostProvider` interface has one method: `current_cost()`.

```python
from governed_agents.interfaces import CostProvider

class LitellmCostProvider(CostProvider):
    """Cost tracking via litellm's completion_cost."""

    def __init__(self):
        self._costs: dict[str, float] = {}
        self._total: float = 0.0

    def current_cost(self, agent_id: str | None = None) -> float:
        if agent_id:
            return self._costs.get(agent_id, 0.0)
        return self._total

    def record_completion(self, response, agent_id: str = "__global__"):
        """Call this from your litellm success callback."""
        import litellm

        cost = litellm.completion_cost(completion_response=response)
        self._costs[agent_id] = self._costs.get(agent_id, 0.0) + cost
        self._total += cost
```

Use it:

```python
from governed_agents.handlers import BudgetGatekeeper

cost_tracker = LitellmCostProvider()
pipeline.add(BudgetGatekeeper(budget_limit_usd=10.0, cost_provider=cost_tracker))

# In your litellm callback:
# cost_tracker.record_completion(response, agent_id="assistant")
```

---

## Implementing AuditBackend (File Example)

The `AuditBackend` interface has one method: `log()`.

```python
import json
from governed_agents.interfaces import AuditBackend, AuditEntry

class FileAuditBackend(AuditBackend):
    """Append audit entries to a JSONL file."""

    def __init__(self, path: str = "audit.jsonl"):
        self._path = path

    async def log(self, entry: AuditEntry) -> None:
        record = {
            "timestamp": entry.timestamp,
            "action": entry.action,
            "agent_id": entry.agent_id,
            "vt_tier": entry.vt_tier,
            "verdict": entry.verdict,
            "handler_name": entry.handler_name,
            "reason": entry.reason,
            "metadata": entry.metadata,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(record) + "\n")
```

Use it:

```python
from governed_agents.handlers import AuditLogger

pipeline.add(
    AuditLogger(backend=FileAuditBackend("governance-audit.jsonl")),
    optional=True,
)
```

---

## Implementing ApprovalBackend (Slack Stub)

The `ApprovalBackend` interface has three methods: `request_approval()`, `check_approval()`, and `cancel_approval()`. This is the interface for routing VT2+ actions to humans.

```python
from governed_agents.approval import (
    ApprovalBackend,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
)

class SlackApprovalBackend(ApprovalBackend):
    """Route approval requests to a Slack channel.

    This is a stub showing the interface. A real implementation
    would use the Slack API to post interactive messages and
    poll for responses.
    """

    def __init__(self, channel: str, bot_token: str):
        self._channel = channel
        self._token = bot_token
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(self, request: ApprovalRequest) -> None:
        self._pending[request.trace_id] = request
        # Post to Slack with interactive buttons
        # slack_client.chat_postMessage(
        #     channel=self._channel,
        #     text=f"Approval needed: {request.summary}",
        #     blocks=[...interactive blocks...],
        # )

    async def check_approval(self, trace_id: str) -> ApprovalResponse | None:
        # Poll Slack for button click response
        # If responded, return ApprovalResponse
        # If still pending, return None
        return None

    async def cancel_approval(self, trace_id: str) -> None:
        self._pending.pop(trace_id, None)
        # Update Slack message to show cancellation
```

!!! note
    `governed-agents` does not include a Slack implementation. The library provides the contract; you provide the integration with your specific communication channels.

---

## Implementing RateLimitPolicy (Redis Example)

```python
from governed_agents.interfaces import RateLimitPolicy

class RedisRateLimitPolicy(RateLimitPolicy):
    """Distributed rate limiting via Redis sorted sets."""

    def __init__(self, redis_client, max_per_window: int = 10, window_seconds: int = 60):
        self._redis = redis_client
        self._max = max_per_window
        self._window = window_seconds

    async def check(self, agent_id: str, action: str) -> bool:
        import time
        key = f"rate:{agent_id}:{action}"
        now = time.time()
        cutoff = now - self._window

        # Remove expired entries
        await self._redis.zremrangebyscore(key, 0, cutoff)

        # Count current entries
        count = await self._redis.zcard(key)
        return count < self._max

    async def record(self, agent_id: str, action: str) -> None:
        import time
        key = f"rate:{agent_id}:{action}"
        now = time.time()
        await self._redis.zadd(key, {str(now): now})
        await self._redis.expire(key, self._window)
```

---

## Design Principle

The pattern is always the same:

1. Define an abstract interface (`PIIDetector`, `CostProvider`, etc.)
2. Provide a zero-dependency built-in default for development
3. Accept any implementation of the interface via constructor injection
4. The governance *logic* (when to block, what tier to enforce) never changes

This means you can swap from regex PII detection to Presidio, or from in-memory rate limiting to Redis, without touching your governance pipeline configuration.
