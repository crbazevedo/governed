# Decorator

The `@governed` decorator is the simplest way to add governance to any function. Two lines of setup, one decorator per function.

## Basic Usage

```python
from governed_agents.decorator import governed, configure, GovernanceError
from governed_agents import VTGovernanceHandler
from governed_agents.handlers import PIIFilter

# Configure once at startup
configure(handlers=[PIIFilter(), VTGovernanceHandler()])

# Decorate functions with their VT tier
@governed(vt=1)
async def search_docs(query: str) -> str:
    return f"Results for: {query}"

@governed(vt=2)
async def send_email(to: str, body: str) -> str:
    return f"Sent to {to}"

await search_docs(query="revenue")         # Executes (VT1: log & proceed)
await send_email(to="c@x.com", body="Hi")  # Raises GovernanceError
```

## configure()

Call `configure()` once at application startup. It sets the module-level default pipeline that all `@governed` functions use.

```python
# Option 1: pass handler instances (auto-priority)
configure(handlers=[PIIFilter(), RateLimiter(), VTGovernanceHandler()])

# Option 2: pass a pre-built pipeline
pipeline = GovernancePipeline()
pipeline.add(PIIFilter())
pipeline.register(RateLimiter(), priority=10, mode=ExecutionMode.PARALLEL)
pipeline.add(VTGovernanceHandler())
configure(pipeline=pipeline)
```

`configure()` returns the pipeline for chaining or inspection:

```python
p = configure(handlers=[PIIFilter(), VTGovernanceHandler()])
print(len(p.handlers))  # 2
```

## @governed() Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vt` | `int` | `1` | VT risk tier for this function (0-4) |
| `pii` | `bool` | `False` | Prepend a PIIFilter for this call |
| `domain` | `str` | `""` | Domain scope tag (e.g., "corporate") |
| `action` | `str` | `""` | Override action name (defaults to function name) |
| `agent_id` | `str` | `""` | Override agent ID in the context |

### Per-call PII filtering

When `pii=True`, a `PIIFilter` is prepended to the pipeline for this specific call, even if the default pipeline does not include one:

```python
@governed(vt=1, pii=True)
async def process_user_data(name: str, email: str) -> str:
    # email will be redacted before this function executes
    return f"Processed {name}"
```

### Domain scoping

The `domain` parameter sets `metadata["domain_scope"]` in the `ActionContext`, which `DomainBarrierHandler` can use for cross-domain isolation:

```python
@governed(vt=1, domain="personal")
async def check_calendar() -> str:
    return "Your schedule..."

@governed(vt=2, domain="corporate")
async def send_client_email(to: str, body: str) -> str:
    return f"Sent to {to}"
```

## GovernanceError Handling

When a `@governed` function is blocked, it raises `GovernanceError` with structured recovery information:

```python
try:
    await send_email(to="client@corp.com", body="Proposal")
except GovernanceError as e:
    # Human-readable
    print(str(e))           # The reason string
    print(e.suggestion)     # "Request approval via ApprovalBackend..."
    print(e.alternatives)   # ["Lower VT tier to VT1", "Request pre-approval"]

    # Programmatic
    if e.recovery:
        print(e.recovery.primary)       # RecoveryAction.RETRY_WITH_APPROVAL
        print(e.recovery.alternatives)  # [DOWNGRADE_TO_ADVISORY, DELEGATE_TO_HUMAN]

    # Full result access
    print(e.result.handler_name)  # "vt_governance"
    print(e.result.action)        # Verdict.BLOCK
```

## Sync and Async Support

The decorator works with both sync and async functions:

```python
@governed(vt=1)
async def async_search(query: str) -> str:
    return f"Results for: {query}"

@governed(vt=1)
def sync_search(query: str) -> str:
    return f"Results for: {query}"

# Both work
await async_search(query="test")  # Async context
sync_search(query="test")          # Sync context (uses asyncio.run internally)
```

!!! warning "Sync from async"
    Calling a sync `@governed` function from inside an async context (running event loop) raises `RuntimeError`. Use the async version instead.

## Context Propagation

When a pipeline handler modifies the context (e.g., PIIFilter redacts the payload), the modified values are propagated back to the function's arguments:

```python
@governed(vt=1, pii=True)
async def greet(name: str, email: str) -> str:
    # If email contained PII, it will be "[REDACTED]" here
    return f"Hello {name}, your email is {email}"

result = await greet(name="Alice", email="alice@example.com")
# result == "Hello Alice, your email is [REDACTED]"
```

## Testing

Use `reset_pipeline()` to clean up between tests:

```python
from governed_agents.decorator import reset_pipeline

def teardown():
    reset_pipeline()
```

Or use `get_pipeline()` to inspect the current configuration:

```python
from governed_agents.decorator import get_pipeline

p = get_pipeline()
print([r.handler.name for r in p.handlers])
```
