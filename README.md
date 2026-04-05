# governed-agents

[![CI](https://github.com/crbazevedo/governed/actions/workflows/ci.yml/badge.svg)](https://github.com/crbazevedo/governed/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Other tools set guardrails. We calibrate autonomy.**

Governed-agents is a Python library for principled autonomy delegation in AI agent systems. It provides the governance **model** — risk-tiered authorization, temporal action windows, decision debt tracking, and cross-domain information barriers — while letting you plug in your own infrastructure for PII detection, cost tracking, audit logging, and human approval routing.

**Full pipeline: 0.022ms p50. 45,000 executions/sec. Zero-overhead tracing.**

## Install

```bash
pip install governed-agents
```

Optional extras:

```bash
pip install governed-agents[amo]       # AMO dynamic VT optimization (minimal-oversight)
pip install governed-agents[presidio]  # Presidio PII detection backend
```

## Quick Start

### The decorator (simplest)

```python
from governed_agents.decorator import governed, configure, GovernanceError
from governed_agents import VTGovernanceHandler
from governed_agents.handlers import PIIFilter

configure(handlers=[PIIFilter(), VTGovernanceHandler()])

@governed(vt=1)
async def search_docs(query: str):
    return f"Results for: {query}"

@governed(vt=2)
async def send_email(to: str, body: str):
    return f"Sent to {to}"

await search_docs(query="revenue")        # Executes (VT1: log & proceed)
await send_email(to="c@x.com", body="Hi") # Raises GovernanceError (VT2: needs approval)
```

The `GovernanceError` includes recovery guidance:

```python
try:
    await send_email(to="client@corp.com", body="Proposal")
except GovernanceError as e:
    print(e.suggestion)    # "Request approval via ApprovalBackend..."
    print(e.alternatives)  # ["Lower VT tier to VT1", "Request pre-approval"]
```

### The pipeline (full control)

```python
import asyncio
from governed_agents import GovernancePipeline, ActionContext, VTGovernanceHandler, Verdict
from governed_agents.handlers import PIIFilter, RateLimiter, AuditLogger

async def main():
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(RateLimiter(max_per_window=10))
    pipeline.add(VTGovernanceHandler())
    pipeline.add(AuditLogger(), optional=True)

    ctx = ActionContext(action="send_email", agent_id="assistant", vt_tier=2,
                        payload={"to": "client@corp.com", "body": "Proposal"})

    # Simple result
    result = await pipeline.execute(ctx)
    print(result.action)       # Verdict.BLOCK
    print(result.suggestion)   # "Request approval via ApprovalBackend..."
    print(result.alternatives) # ["Lower VT tier", "Request pre-approval"]

    # Full execution trace
    trace = await pipeline.execute_traced(ctx)
    print(trace.summary)  # "block (0.02ms, 4 handlers: pii_filter, rate_limiter, ...)"
    for ht in trace.handler_traces:
        print(f"  {ht.handler_name}: {ht.verdict.value} ({ht.duration_ms:.2f}ms)")

asyncio.run(main())
```

### From TOML config (declarative)

```toml
# governance.toml
[profile]
domain = "corporate"
default_vt = 2

[profile.vt_floor]
read_data = 0
send_email = 2
deploy = 3
delete_data = 4

[pipeline]
handlers = ["pii", "rate_limiter", "vt", "audit"]

[pipeline.rate_limiter]
max_per_window = 10
window_seconds = 60
```

```python
from governed_agents.profile_loader import load_pipeline_config

pipeline = load_pipeline_config("governance.toml")
```

## VT Risk Tiers

The Verified Trust (VT) tier system controls agent autonomy with five graduated levels:

| Tier | Label | Behavior | Agent Can |
|------|-------|----------|-----------|
| VT0 | Autonomous | No restrictions | Act freely |
| VT1 | Log & Proceed | Action logged for review | Act, with audit trail |
| VT2 | Require Approval | Human must approve | Propose, not execute |
| VT3 | Advise Only | Agent can only recommend | Present options |
| VT4 | Owner Only | Blocked entirely | Nothing — human only |

Default: VT1 (log & proceed). Forgetting to set a tier results in logging, not silent bypass.

## Three Layers

The library is organized in three layers. Use only what you need.

### Layer 1: Static (stateless, zero-dep handlers)

Stateless policy enforcement. Any framework, 5-minute adoption.

```python
from governed_agents import VTGovernanceHandler       # Risk tier enforcement
from governed_agents.handlers import PIIFilter        # PII detection/redaction
from governed_agents.handlers import ComplianceChecker # Payload validation
from governed_agents.handlers import UXHandler         # HITL message formatting
```

### Layer 2: Dynamic (stateful runtime)

Track state across invocations. Governance that evolves over time.

```python
from governed_agents.handlers import RateLimiter       # Sliding window per agent
from governed_agents.handlers import BudgetGatekeeper   # Cumulative cost enforcement
from governed_agents.aow import AOWWindow, AOWHandler   # Time-bounded action windows
from governed_agents.decision_debt import DecisionDebt, DecisionDebtLedger  # Deferred decision tracking
from governed_agents.domain import GovernanceProfile, DomainBarrierHandler  # Cross-domain barriers
```

### Layer 3: Persistent (integration interfaces)

Plug in your infrastructure. We define the contract, you provide the implementation.

```python
from governed_agents.interfaces import PIIDetector       # Presidio, AWS Comprehend, regex (built-in)
from governed_agents.interfaces import RateLimitPolicy   # Redis, API gateway, in-memory (built-in)
from governed_agents.interfaces import CostProvider      # litellm, LangSmith, manual (built-in)
from governed_agents.interfaces import AuditBackend      # File, Redis, SIEM, logging (built-in)
from governed_agents.approval import ApprovalBackend     # Slack, CLI, web UI
from governed_agents.interfaces import DebtStore         # Redis, PostgreSQL, SQLite
```

## Key Features

### Structured rejection feedback

Every blocked action includes actionable recovery guidance:

```python
result = await pipeline.execute(ctx)
if result.action == Verdict.BLOCK:
    print(result.suggestion)    # "Wait 12s before retrying"
    print(result.alternatives)  # ["Reduce action frequency", "Batch actions"]
```

### Action Opportunity Windows (AOW)

Time-bounded governance — control WHEN actions can happen, not just WHETHER:

```python
from governed_agents.aow import AOWWindow, AOWState
from datetime import datetime, timedelta, timezone

window = AOWWindow(
    action_id="deploy",
    earliest=datetime.now(timezone.utc),
    latest=datetime.now(timezone.utc) + timedelta(hours=2),
)
state = window.evaluate()  # AOWState.OPEN → AOWState.EXPIRING → AOWState.EXPIRED
```

Terminal states are latched: once expired, always expired.

### Decision Debt

Deferred decisions accumulate risk with automatic escalation:

```python
from governed_agents.decision_debt import DecisionDebt, DecisionDebtLedger

debt = DecisionDebt(
    debt_id="D001", action="deploy", agent_id="eng",
    vt_tier=2, summary="Deploy to production",
    max_deferrals=3, escalation_threshold=0.5,
)
debt.defer("Not ready")   # deferral_count=1, state=DEFERRED
debt.defer("Still busy")  # deferral_count=2
debt.defer("Later")       # deferral_count=3 → state=ESCALATED (auto)
```

### BYOPA Domain Barriers

Cross-domain personal/corporate information barriers:

```python
from governed_agents.domain import GovernanceProfile, DomainBarrierHandler

personal = GovernanceProfile(domain="personal", vt_floor={"send_email": 1})
corporate = GovernanceProfile(domain="corporate", vt_floor={"send_email": 2})

barrier = DomainBarrierHandler(profiles={"personal": personal, "corporate": corporate})
# Cross-domain actions: content fields stripped, only metadata passes through
```

### Pluggable backends

Every infrastructure concern is an interface. Swap implementations without changing governance logic:

```python
from governed_agents.interfaces import PIIDetector, PIIMatch

class PresidioPIIDetector(PIIDetector):
    def scan(self, payload): ...   # Use Microsoft Presidio
    def redact(self, payload): ... # Use Presidio anonymizer

pipeline.add(PIIFilter(detector=PresidioPIIDetector()))  # Same governance, better PII
```

Built-in defaults (zero deps): `RegexPIIDetector`, `InMemoryRateLimit`, `ManualCostTracker`, `LogAuditBackend`.

## Framework Integration

Working examples in [`examples/`](examples/):

| Example | Framework | What it shows |
|---------|-----------|---------------|
| [`quickstart.py`](examples/quickstart.py) | None | Pipeline, trace, decorator |
| [`pydantic_ai_example.py`](examples/pydantic_ai_example.py) | Pydantic AI | Wrap tool calls with governance |
| [`langgraph_example.py`](examples/langgraph_example.py) | LangGraph | Governance as a workflow node |
| [`anthropic_sdk_example.py`](examples/anthropic_sdk_example.py) | Anthropic SDK | Govern Claude tool_use calls |
| [`dynamic_example.py`](examples/dynamic_example.py) | None | AOW windows + Decision Debt |
| [`domain_barrier_example.py`](examples/domain_barrier_example.py) | None | BYOPA cross-domain barriers |
| [`custom_backend_example.py`](examples/custom_backend_example.py) | None | Custom PIIDetector, CostProvider, AuditBackend |
| [`toml_config_example.py`](examples/toml_config_example.py) | None | Declarative TOML governance profiles |

All examples are self-contained and runnable without API keys.

## Performance

Benchmarked on Apple Silicon (M-series), Python 3.12:

| Benchmark | p50 | p95 | p99 | Throughput |
|-----------|-----|-----|-----|-----------|
| Empty pipeline | 0.001ms | 0.001ms | 0.001ms | — |
| Single handler | 0.003ms | 0.003ms | 0.004ms | — |
| Full pipeline (5 handlers) | 0.022ms | 0.028ms | 0.032ms | 45,000/sec |
| Full pipeline + tracing | 0.022ms | 0.027ms | 0.031ms | — |

Tracing adds zero measurable overhead.

Run benchmarks locally: `python benchmarks/bench_pipeline.py`

## Optional: AMO Integration

The [Axiom of Minimal Oversight](https://github.com/crbazevedo/delegation-lab) replaces static VT tiers with information-theoretic authority allocation. Instead of hardcoding "this action is VT2," the AMO computes the optimal oversight level based on measured agent competence.

```bash
pip install governed-agents[amo]
```

```python
from governed_agents._amo import DynamicVTHandler

pipeline = GovernancePipeline()
pipeline.add(DynamicVTHandler(p_min=0.80))  # Before VTGovernanceHandler
pipeline.add(VTGovernanceHandler())

# Agent competence provided via metadata:
ctx = ActionContext(
    action="deploy", agent_id="eng", vt_tier=2,
    metadata={"sigma_skill": 0.82, "catch_rate": 0.70},
)
# AMO may adjust VT2 → VT1 if the agent's competence warrants it
```

Reference: Azevedo, C.R.B. (2026). *"Minimal Oversight: A Theory of Principled Autonomy Delegation."*

## How It Compares

| Feature | governed-agents | MS Agent Gov Toolkit | Salus | NeMo Guardrails |
|---------|:-:|:-:|:-:|:-:|
| Risk-tiered autonomy (VT0-VT4) | Yes | Partial | No | No |
| Temporal governance (AOW) | Yes | No | No | No |
| Decision Debt tracking | Yes | No | No | No |
| Cross-domain barriers (BYOPA) | Yes | No | No | No |
| Structured rejection feedback | Yes | No | Yes (self-repair) | No |
| Pipeline execution traces | Yes | Partial | No | No |
| Declarative config (TOML) | Yes | Yes | Yes (YAML) | Yes (Colang) |
| `@governed` decorator | Yes | No | No | No |
| Information-theoretic foundation | Yes (paper) | No | No | No |
| Interface-first architecture | Yes | No | No (SaaS) | No |
| Sub-0.1ms pipeline latency | Yes (0.022ms) | Yes (<0.1ms) | No (API) | No |

See [`docs/COMPETITIVE-LANDSCAPE.md`](docs/COMPETITIVE-LANDSCAPE.md) for the full analysis.

## Custom Handlers

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
                suggestion="Remove or redact confidential content before proceeding",
                alternatives=["Redact content", "Request clearance", "Use a summary instead"],
            )
        return GovernanceResult.continue_(handler_name=self.name)
```

## License

MIT -- Copyright (c) 2026 Carlos R. B. Azevedo

## Citation

```bibtex
@software{azevedo2026governed,
  title={governed-agents: Governed Autonomy Middleware for AI Agent Systems},
  author={Azevedo, Carlos R. B.},
  year={2026},
  url={https://github.com/crbazevedo/governed}
}
```
