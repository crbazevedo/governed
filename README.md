# governed-agents

Governed autonomy middleware for AI agent systems. Drop a governance pipeline into any Python agent framework -- enforce VT risk tiers, redact PII, gate on budgets, rate-limit actions, and escalate to humans when it matters. Works with Pydantic AI, LangGraph, CrewAI, Google ADK, or your own framework.

## Install

```bash
pip install governed-agents
```

Optional extras:

```bash
pip install governed-agents[redis]   # Redis-backed audit logging
pip install governed-agents[viz]     # Rich terminal output
pip install governed-agents[amo]     # AMO dynamic VT optimization
pip install governed-agents[all]     # Everything
```

## Quick Start

```python
import asyncio
from governed_agents import CallbackPipeline, CallbackContext, VTGovernanceHandler
from governed_agents.handlers import PIIFilter, AuditLogger, RateLimiter

async def main():
    pipeline = CallbackPipeline()
    pipeline.register(PIIFilter(), priority=10)
    pipeline.register(RateLimiter(max_concurrent=3), priority=10)
    pipeline.register(VTGovernanceHandler(), priority=20)
    pipeline.register(AuditLogger(backend="json", path="audit.jsonl"), priority=40, optional=True)

    ctx = CallbackContext(action="send_email", agent_id="assistant", vt_tier=2,
                          payload={"to": "client@corp.com", "body": "Proposal"})
    result = await pipeline.execute(ctx)
    print(result.action)  # "abort" -- VT2 requires human approval

asyncio.run(main())
```

## VT Risk Tiers

The Verified Trust (VT) tier system controls agent autonomy:

| Tier | Label | Behavior |
|------|-------|----------|
| VT0 | Autonomous | Agent acts freely, no restrictions |
| VT1 | Log & Proceed | Agent acts, action logged for review |
| VT2 | Require Approval | Agent proposes, human must approve |
| VT3 | Advise Only | Agent can only advise, cannot execute |
| VT4 | Owner Only | Blocked -- only a human can perform this |

## Built-in Handlers

| Handler | Priority | Purpose |
|---------|----------|---------|
| `PIIFilter` | 10 | Detect and redact PII (email, phone, SSN, CPF, credit card) |
| `RateLimiter` | 10 | Sliding window rate limiting per agent |
| `BudgetGatekeeper` | 10 | Cumulative cost enforcement |
| `UXHandler` | 15 | Format VT2+ actions as HITL messages |
| `VTGovernanceHandler` | 20 | Enforce VT tier policies |
| `ComplianceChecker` | 50 | Payload size, VT consistency, audit readiness |
| `AuditLogger` | 40 | JSON file or Redis stream audit trail |

## Framework Integration

### Pydantic AI

```python
from pydantic_ai import Agent
from governed_agents import CallbackPipeline, CallbackContext, VTGovernanceHandler

pipeline = CallbackPipeline()
pipeline.register(VTGovernanceHandler(), priority=20)

@agent.tool
async def governed_tool(ctx):
    result = await pipeline.execute(CallbackContext(action="tool_call", vt_tier=1))
    if result.action.value == "abort":
        return f"Blocked: {result.reason}"
    # ... proceed with tool logic
```

### LangGraph

```python
from langgraph.graph import StateGraph
from governed_agents import CallbackPipeline, CallbackContext, VTGovernanceHandler

pipeline = CallbackPipeline()
pipeline.register(VTGovernanceHandler(), priority=20)

async def governance_node(state):
    result = await pipeline.execute(
        CallbackContext(action=state["action"], vt_tier=state.get("vt_tier", 1))
    )
    return {**state, "governance_result": result.action.value}
```

### CrewAI

```python
from crewai import Task
from governed_agents import CallbackPipeline, CallbackContext, VTGovernanceHandler

pipeline = CallbackPipeline()
pipeline.register(VTGovernanceHandler(), priority=20)

async def governed_task_callback(output):
    result = await pipeline.execute(
        CallbackContext(action="task_output", vt_tier=1, payload={"output": str(output)})
    )
    return result.action.value != "abort"
```

## Custom Handlers

```python
from governed_agents import CallbackHandler, CallbackContext, CallbackResult

class MyCustomHandler(CallbackHandler):
    @property
    def name(self) -> str:
        return "my_handler"

    async def check(self, context: CallbackContext) -> CallbackResult:
        if context.payload.get("sensitive"):
            return CallbackResult.abort(handler_name=self.name, reason="Sensitive data detected")
        return CallbackResult.continue_(handler_name=self.name)

pipeline.register(MyCustomHandler(), priority=25)
```

## Pipeline Features

- **Priority-ordered groups**: Handlers execute in priority order (lower first)
- **Mixed execution**: Parallel within groups, sequential across groups
- **Abort short-circuit**: Any handler can halt the entire pipeline
- **Context chaining**: Handlers can modify context for downstream handlers
- **Graceful degradation**: Optional handlers fail silently; required handlers abort on error
- **Dependency resolution**: Handlers can declare dependencies on other handlers

## Optional: AMO Integration

With the [Autonomous Multi-agent Oversight](https://github.com/crbazevedo/minimal-oversight) library, replace static VT tiers with dynamic water-filling optimization:

```bash
pip install governed-agents[amo]
```

```python
from governed_agents._amo import DynamicVTHandler

pipeline.register(DynamicVTHandler(safety_budget=0.8), priority=5)
```

## License

MIT -- Copyright (c) 2026 Carlos R. B. Azevedo
