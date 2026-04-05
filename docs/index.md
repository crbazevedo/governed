# governed-agents

**Governed autonomy middleware for AI agent systems.**

`governed-agents` is a Python library that controls *how much* autonomy your AI agents have -- not just what they can say, but what they can *do*, when they can do it, and how much damage they can cause if they get it wrong. It provides risk-tiered authorization (VT0-VT4), temporal action windows, decision debt tracking, trust evolution, and cross-domain information barriers, while letting you plug in your own infrastructure for PII detection, cost tracking, audit logging, and human approval routing.

> Other tools set guardrails. We calibrate autonomy.

## Install

```bash
pip install governed-agents
```

## Quick Start

```python
from governed_agents import GovernancePipeline, ActionContext, VTGovernanceHandler
from governed_agents.handlers import PIIFilter, RateLimiter, AuditLogger

pipeline = GovernancePipeline()
pipeline.add(PIIFilter())
pipeline.add(RateLimiter(max_per_window=10))
pipeline.add(VTGovernanceHandler())
pipeline.add(AuditLogger(), optional=True)

ctx = ActionContext(action="send_email", agent_id="assistant", vt_tier=2,
                    payload={"to": "client@corp.com", "body": "Proposal"})

result = await pipeline.execute(ctx)
# result.action == Verdict.BLOCK (VT2 needs approval)
# result.suggestion == "Request approval via ApprovalBackend..."
# result.alternatives == ["Lower VT tier to VT1", "Request pre-approval"]
```

Or use the decorator for zero-boilerplate governance:

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

await search_docs(query="revenue")         # Executes (VT1: log & proceed)
await send_email(to="c@x.com", body="Hi")  # Raises GovernanceError (VT2: needs approval)
```

## Performance

Benchmarked on Apple Silicon (M-series), Python 3.12:

| Benchmark | p50 | p95 | p99 | Throughput |
|-----------|-----|-----|-----|-----------|
| Empty pipeline | 0.001ms | 0.001ms | 0.001ms | -- |
| Single handler | 0.003ms | 0.003ms | 0.004ms | -- |
| Full pipeline (5 handlers) | 0.022ms | 0.028ms | 0.032ms | 45,000/sec |
| Full pipeline + tracing | 0.022ms | 0.027ms | 0.031ms | -- |

Tracing adds zero measurable overhead. Run benchmarks locally: `python benchmarks/bench_pipeline.py`

## What's Next

- [Principles](PRINCIPLES.md) -- the nine design principles and their academic grounding
- [Getting Started](guide/getting-started.md) -- your first governed pipeline in five minutes
- [Theory](theory.md) -- connection to the Minimal Oversight paper
- [Comparisons](comparisons.md) -- how we differ from Microsoft Agent Gov Toolkit, Salus, NeMo, and others
