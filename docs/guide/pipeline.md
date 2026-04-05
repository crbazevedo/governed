# Pipeline

The `GovernancePipeline` is the middleware chain that evaluates actions against a sequence of governance handlers.

## How It Works

The pipeline processes handlers group-by-group in priority order:

```
Action arrives
  |
  v
[Priority 10: PIIFilter + RateLimiter]  <-- parallel group
  |
  v
[Priority 20: VTGovernanceHandler]       <-- sequential
  |
  v
[Priority 30: AuditLogger]              <-- sequential, optional
  |
  v
Result: ALLOW / BLOCK / MODIFY
```

Key behaviors:

- **Priority groups:** Handlers are grouped by priority (lower runs first). Within a group, if all handlers are registered as `PARALLEL`, they run concurrently via `asyncio.gather`.
- **Block short-circuits:** Any handler returning `BLOCK` halts the entire pipeline immediately.
- **Context modification chaining:** A handler returning `MODIFY` transforms the `ActionContext` for all downstream handlers (e.g., PIIFilter redacts the payload before VTGovernanceHandler sees it).
- **Graceful degradation:** Handler exceptions are caught and logged. Optional handlers are skipped on failure. Non-optional handler failures are treated as `BLOCK` to prevent silent bypass.

## pipeline.add() vs pipeline.register()

### `pipeline.add()` -- simple, auto-priority

```python
pipeline = GovernancePipeline()
pipeline.add(PIIFilter())                          # priority 10
pipeline.add(RateLimiter(max_per_window=10))       # priority 20
pipeline.add(VTGovernanceHandler())                # priority 30
pipeline.add(AuditLogger(), optional=True)          # priority 40
```

`add()` auto-assigns priority in increments of 10. Handlers run in the order you add them. Use the `optional` keyword to mark handlers whose failure should not block the pipeline.

### `pipeline.register()` -- explicit priority and mode

```python
from governed_agents import ExecutionMode

pipeline = GovernancePipeline()
pipeline.register(PIIFilter(), priority=10, mode=ExecutionMode.PARALLEL)
pipeline.register(RateLimiter(max_per_window=10), priority=10, mode=ExecutionMode.PARALLEL)
pipeline.register(VTGovernanceHandler(), priority=20)
pipeline.register(AuditLogger(), priority=30, optional=True)
```

Use `register()` when you need:

- **Parallel execution:** Multiple handlers at the same priority with `mode=ExecutionMode.PARALLEL`
- **Explicit ordering:** Fine-grained control over which handlers run when
- **Dependencies:** `depends_on=frozenset({"pii_filter"})` ensures a handler only runs after named dependencies complete

## Execution Flow

```
pipeline.execute(ctx)
  |
  +--> Group by priority
  |
  +--> For each group (ascending priority):
  |      |
  |      +--> Check depends_on (defer unmet to next group)
  |      |
  |      +--> All PARALLEL? --> asyncio.gather()
  |      |    Otherwise     --> sequential loop
  |      |
  |      +--> For each result:
  |             BLOCK  --> return immediately
  |             MODIFY --> update ctx for downstream
  |             ALLOW  --> continue
  |
  +--> All passed --> return ALLOW
```

## ExecutionTrace and Introspection

Use `execute_traced()` for full visibility into what happened:

```python
trace = await pipeline.execute_traced(ctx)

print(trace.summary)
# "allow (0.03ms, 4 handlers: pii_filter, rate_limiter, vt_governance, audit_logger)"

print(trace.final_verdict)       # Verdict.ALLOW
print(trace.total_duration_ms)   # 0.03
print(trace.context_modifications)  # 2 (PII redaction + VT metadata)

for ht in trace.handler_traces:
    print(f"  {ht.handler_name}: {ht.verdict.value} ({ht.duration_ms:.3f}ms)")
    if ht.suggestion:
        print(f"    Suggestion: {ht.suggestion}")
```

The `ExecutionTrace` captures:

| Field | Type | Description |
|-------|------|-------------|
| `final_verdict` | `Verdict` | Pipeline outcome: ALLOW or BLOCK |
| `final_reason` | `str` | Why the pipeline reached this verdict |
| `handler_traces` | `list[HandlerTrace]` | Per-handler details |
| `total_duration_ms` | `float` | Total pipeline execution time |
| `context_modifications` | `int` | Number of MODIFY results applied |
| `suggestion` | `str` | Recovery hint (for BLOCK verdicts) |
| `alternatives` | `list[str]` | Alternative approaches (for BLOCK verdicts) |

Each `HandlerTrace` contains:

| Field | Type | Description |
|-------|------|-------------|
| `handler_name` | `str` | Handler that produced this trace |
| `verdict` | `Verdict` | This handler's verdict |
| `reason` | `str` | Why this handler reached its verdict |
| `duration_ms` | `float` | Execution time for this handler |
| `suggestion` | `str` | Recovery suggestion |
| `alternatives` | `list[str]` | Alternative actions |

## execute_with_context()

When you need the final (possibly modified) context after all handlers run -- for example, to use the PII-redacted payload:

```python
result, final_ctx = await pipeline.execute_with_context(ctx)

if result.action != Verdict.BLOCK:
    # final_ctx.payload has been PII-redacted by PIIFilter
    send_message(final_ctx.payload["body"])
```

## Writing Custom Handlers

Every handler extends `GovernanceHandler`:

```python
from governed_agents import GovernanceHandler, ActionContext, GovernanceResult

class ContentPolicyHandler(GovernanceHandler):
    @property
    def name(self) -> str:
        return "content_policy"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        if "confidential" in str(context.payload).lower():
            return GovernanceResult.abort(
                handler_name=self.name,
                reason="Confidential content detected",
                suggestion="Remove or redact confidential content",
                alternatives=["Redact content", "Request clearance"],
            )
        return GovernanceResult.continue_(handler_name=self.name)
```

See [Handlers](handlers.md) for the built-in handler inventory and [Custom Backends](custom-backends.md) for implementing pluggable infrastructure.
