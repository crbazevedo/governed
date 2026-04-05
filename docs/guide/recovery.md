# Recovery

When governance blocks an action, the system provides structured recovery paths that agents can programmatically attempt -- not just human-readable error strings.

This implements [Principle 5: Graceful Degradation](../PRINCIPLES.md#5-graceful-degradation).

## The Problem: Opaque Failures vs Structured Recovery

Most governance systems return a binary result: allowed or denied. When denied, the agent gets a reason string -- `"Rate limit exceeded"` -- but no guidance on what to do next.

The agent's options are: retry blindly, give up, or ask a human. All three waste time.

`governed-agents` returns structured recovery plans with every BLOCK verdict. The agent (or the framework wrapping it) can inspect the plan and attempt automatic recovery.

## RecoveryAction Enum

Every recovery strategy has a typed name:

| Action | When to Use |
|--------|-------------|
| `RETRY_WITH_APPROVAL` | Action was blocked by VT tier. Get human approval and retry. |
| `RETRY_LOWER_SCOPE` | Action was too broad. Reduce scope and retry. |
| `RETRY_AFTER_DELAY` | Rate limit or temporal constraint. Wait and retry. |
| `DELEGATE_TO_HUMAN` | Agent cannot handle this. Route to a human. |
| `DOWNGRADE_TO_ADVISORY` | VT3/VT4 block. Present a recommendation instead. |
| `BATCH_WITH_OTHERS` | Frequency limit. Combine with other pending actions. |
| `USE_CHEAPER_RESOURCE` | Budget limit. Switch to a cheaper model or tool. |
| `SPLIT_ACTION` | Action is too large. Break into smaller parts. |

```python
from governed_agents.recovery import RecoveryAction

# Check what recovery is available
if result.recovery and result.recovery.has(RecoveryAction.RETRY_AFTER_DELAY):
    delay = result.recovery.context.get("delay_seconds", 60)
    await asyncio.sleep(delay)
    result = await pipeline.execute(ctx)  # Retry
```

## RecoveryPlan: Primary + Alternatives + Context

A `RecoveryPlan` is attached to BLOCK results and provides:

- **primary:** The system's best recommendation for recovery.
- **alternatives:** Ranked alternatives if the primary doesn't work.
- **context:** Action-specific data needed for recovery (e.g., delay seconds, blocked scope name).
- **explanation:** Human-readable description of what happened.

```python
from governed_agents.recovery import RecoveryPlan, RecoveryAction

plan = RecoveryPlan(
    primary=RecoveryAction.RETRY_AFTER_DELAY,
    alternatives=[RecoveryAction.BATCH_WITH_OTHERS],
    context={"delay_seconds": 12},
    explanation="Rate limit exceeded for this agent",
)

print(plan.primary)          # RecoveryAction.RETRY_AFTER_DELAY
print(plan.alternatives)     # [RecoveryAction.BATCH_WITH_OTHERS]
print(plan.all_actions)      # [RETRY_AFTER_DELAY, BATCH_WITH_OTHERS]
print(plan.has(RecoveryAction.RETRY_AFTER_DELAY))  # True
```

## Building a Programmatic Recovery Loop

Here is a complete recovery loop that an agent framework can implement:

```python
import asyncio
from governed_agents import GovernancePipeline, ActionContext, Verdict
from governed_agents.recovery import RecoveryAction

async def execute_with_recovery(
    pipeline: GovernancePipeline,
    ctx: ActionContext,
    max_retries: int = 3,
) -> tuple[bool, ActionContext]:
    """Execute an action with automatic recovery on BLOCK."""

    for attempt in range(max_retries):
        result = await pipeline.execute(ctx)

        if result.action == Verdict.ALLOW:
            return True, ctx

        if result.action != Verdict.BLOCK or not result.recovery:
            return False, ctx

        plan = result.recovery

        if plan.primary == RecoveryAction.RETRY_AFTER_DELAY:
            delay = plan.context.get("delay_seconds", 60)
            await asyncio.sleep(delay)
            continue  # Retry same context

        elif plan.primary == RecoveryAction.RETRY_LOWER_SCOPE:
            # Reduce scope -- implementation depends on your action
            max_scope = plan.context.get("max_scope", "staging")
            ctx.metadata["scope"] = max_scope
            continue

        elif plan.primary == RecoveryAction.USE_CHEAPER_RESOURCE:
            # Switch to a cheaper model
            ctx.metadata["model"] = "gpt-4o-mini"
            continue

        elif plan.primary == RecoveryAction.BATCH_WITH_OTHERS:
            # Queue for batching -- return to caller
            return False, ctx

        elif plan.primary == RecoveryAction.DELEGATE_TO_HUMAN:
            # Cannot recover automatically
            return False, ctx

        elif plan.primary == RecoveryAction.DOWNGRADE_TO_ADVISORY:
            # Present as recommendation instead of executing
            ctx.metadata["advisory_mode"] = True
            return False, ctx

        else:
            return False, ctx

    return False, ctx
```

## GovernanceError in the Decorator

When using the `@governed` decorator, BLOCK results raise `GovernanceError` with the full recovery information:

```python
from governed_agents.decorator import governed, configure, GovernanceError
from governed_agents import VTGovernanceHandler
from governed_agents.handlers import PIIFilter

configure(handlers=[PIIFilter(), VTGovernanceHandler()])

@governed(vt=2)
async def send_email(to: str, body: str):
    return f"Sent to {to}"

try:
    await send_email(to="client@corp.com", body="Proposal")
except GovernanceError as e:
    print(e.suggestion)    # "Request approval via ApprovalBackend..."
    print(e.alternatives)  # ["Lower VT tier to VT1", "Request pre-approval"]

    if e.recovery:
        print(e.recovery.primary)  # RecoveryAction.RETRY_WITH_APPROVAL
```

The `GovernanceError` exposes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `result` | `GovernanceResult` | Full governance result |
| `suggestion` | `str` | Actionable fix hint |
| `alternatives` | `list[str]` | Concrete alternatives |
| `recovery` | `RecoveryPlan | None` | Typed recovery plan |

## Which Handlers Produce Recovery Plans

Every built-in handler that can BLOCK provides structured recovery:

| Handler | Primary Recovery | Context |
|---------|-----------------|---------|
| `VTGovernanceHandler` (VT2) | `RETRY_WITH_APPROVAL` | -- |
| `VTGovernanceHandler` (VT3) | `DOWNGRADE_TO_ADVISORY` | -- |
| `VTGovernanceHandler` (VT4) | `DELEGATE_TO_HUMAN` | -- |
| `RateLimiter` | `RETRY_AFTER_DELAY` | `delay_seconds` |
| `BudgetGatekeeper` | `USE_CHEAPER_RESOURCE` | `current_cost`, `limit` |
| `PIIFilter` (block mode) | `RETRY_LOWER_SCOPE` | `pii_fields` |
| `BlastRadiusHandler` | Varies by constraint | Varies |
| `AOWHandler` | `RETRY_AFTER_DELAY` or `DELEGATE_TO_HUMAN` | `opens_at`, `blocked_by` |
