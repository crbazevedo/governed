# Getting Started

This guide walks you through your first governed pipeline in five minutes.

## Prerequisites

- Python 3.10 or later
- pip (or any PEP 517 installer)

## Install

```bash
pip install governed-agents
```

Optional extras:

```bash
pip install governed-agents[amo]       # AMO dynamic VT optimization
pip install governed-agents[presidio]  # Presidio PII detection backend
pip install governed-agents[viz]       # Rich terminal output
```

## Your First Pipeline in 5 Minutes

### Step 1: Create a pipeline

```python
import asyncio
from governed_agents import GovernancePipeline, ActionContext, VTGovernanceHandler, Verdict
from governed_agents.handlers import PIIFilter, RateLimiter, AuditLogger

pipeline = GovernancePipeline()
pipeline.add(PIIFilter())                          # Redact PII in payloads
pipeline.add(RateLimiter(max_per_window=10))       # Max 10 actions per 60s
pipeline.add(VTGovernanceHandler())                # Enforce VT risk tiers
pipeline.add(AuditLogger(), optional=True)          # Log decisions (optional)
```

### Step 2: Create an action context

```python
ctx = ActionContext(
    action="send_notification",
    agent_id="assistant",
    vt_tier=1,  # VT1: log & proceed
    payload={"to": "user@example.com", "body": "Meeting reminder"},
)
```

### Step 3: Execute and inspect

```python
async def main():
    result = await pipeline.execute(ctx)

    if result.action == Verdict.ALLOW:
        print("Action allowed -- proceed with execution")
    elif result.action == Verdict.BLOCK:
        print(f"Action blocked: {result.reason}")
        print(f"Suggestion: {result.suggestion}")
        print(f"Alternatives: {result.alternatives}")

asyncio.run(main())
```

### Step 4: Try a VT2 action

```python
ctx_vt2 = ActionContext(
    action="send_email",
    agent_id="assistant",
    vt_tier=2,  # VT2: requires approval
    payload={"to": "client@corp.com", "body": "Proposal attached"},
)

async def main():
    result = await pipeline.execute(ctx_vt2)
    print(result.action)       # Verdict.BLOCK
    print(result.suggestion)   # "Request approval via ApprovalBackend..."
    print(result.alternatives) # ["Lower VT tier to VT1", "Request pre-approval"]

asyncio.run(main())
```

## Understanding VT Tiers

The Verified Trust (VT) tier system is the core governance model. Five graduated levels control agent autonomy:

| Tier | Label | Behavior | Agent Can |
|------|-------|----------|-----------|
| VT0 | Autonomous | No restrictions | Act freely |
| VT1 | Log & Proceed | Action logged for review | Act, with audit trail |
| VT2 | Require Approval | Human must approve | Propose, not execute |
| VT3 | Advise Only | Agent can only recommend | Present options |
| VT4 | Owner Only | Blocked entirely | Nothing -- human only |

The default tier is VT1. Forgetting to set a tier results in logging, not silent bypass.

!!! tip "Start conservative"
    New agents should start at VT2 or VT3. As they accumulate a track record through the [TrustLedger](trust.md), they can earn lower VT tiers automatically.

## What to Read Next

- [Pipeline](pipeline.md) -- how the pipeline works (priority groups, parallel/sequential execution)
- [Trust & Earned Autonomy](trust.md) -- how agents earn trust over time
- [Decorator](decorator.md) -- the simplest way to govern any function
- [Handlers](handlers.md) -- built-in handlers: PII, rate limiting, budget, audit
- [Configuration](config.md) -- declarative TOML governance profiles
