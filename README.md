# governed-agents

[![CI](https://github.com/crbazevedo/governed/actions/workflows/ci.yml/badge.svg)](https://github.com/crbazevedo/governed/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Other tools set guardrails. We calibrate autonomy.**

## What makes this different

- **Risk-tiered, not binary.** Five VT tiers (VT0-VT4) graduate from full autonomy to human-only, replacing the "allow or block" binary that every other framework defaults to.
- **Recovery that acts, not advises.** When governance blocks an action, the `RecoveryExecutor` automatically retries with lower scope, requests approval, waits out rate limits, or downgrades to advisory mode -- no developer retry logic required.
- **Domain barriers built in.** One agent, two governance profiles (personal vs corporate). Information barriers prevent content leakage across boundaries. Declarative TOML config, not code.

## Install

```bash
pip install governed-agents
```

## Quick start

### The decorator (simplest)

```python
from governed_agents.decorator import governed, configure
from governed_agents import VTGovernanceHandler
from governed_agents.handlers import PIIFilter

configure(handlers=[PIIFilter(), VTGovernanceHandler()])

@governed(vt=1)
async def search_docs(query: str):
    return f"Results for: {query}"

await search_docs(query="revenue")  # Passes -- VT1 logs and proceeds
```

### Pipeline with recovery (the new way)

```python
from governed_agents import GovernancePipeline, ActionContext, VTGovernanceHandler
from governed_agents.executor import RecoveryExecutor
from governed_agents.handlers import PIIFilter, RateLimiter, AuditLogger

pipeline = GovernancePipeline()
pipeline.add(PIIFilter())
pipeline.add(RateLimiter(max_per_window=10))
pipeline.add(VTGovernanceHandler())
pipeline.add(AuditLogger(), optional=True)

executor = RecoveryExecutor(pipeline, max_retries=3)

ctx = ActionContext(action="send_email", agent_id="assistant", vt_tier=2,
                    payload={"to": "client@corp.com", "body": "Proposal"})

outcome = await executor.execute(ctx)
if outcome.succeeded:
    print(f"Passed after {outcome.attempts} attempt(s)")
else:
    print(f"Blocked. Recovery tried: {outcome.recovery_actions_taken}")
```

The executor automatically attempts recovery strategies: delays for rate limits, scope reduction for PII, VT downgrade for advisory mode, and approval workflows for VT2+ actions.

### From TOML config (declarative, multi-domain)

```toml
# governance.toml
[domains.personal]
default_vt = 1

[domains.personal.vt_floor]
send_email = 1

[domains.corporate]
default_vt = 2

[domains.corporate.vt_floor]
send_email = 2
deploy = 3

[barrier]
allowed_fields = ["timestamp", "urgency"]

[pipeline]
handlers = ["pii", "vt", "audit"]
```

```python
from governed_agents.profile_loader import load_domain_config

cfg = load_domain_config("governance.toml")
result = await cfg.pipeline.execute(ctx)
```

## VT risk tiers

| Tier | Label | Behavior | Agent can |
|------|-------|----------|-----------|
| VT0 | Autonomous | No restrictions | Act freely |
| VT1 | Log & Proceed | Action logged for review | Act, with audit trail |
| VT2 | Require Approval | Human must approve | Propose, not execute |
| VT3 | Advise Only | Agent can only recommend | Present options |
| VT4 | Owner Only | Blocked entirely | Nothing -- human only |

Default: VT1. Forgetting to set a tier results in logging, not silent bypass.

## The 9 principles

1. [Calibrated Autonomy](https://crbazevedo.github.io/governed/theory/principles/) -- Match oversight to demonstrated competence
2. [Masking Transparency](https://crbazevedo.github.io/governed/theory/principles/) -- Detect when human corrections hide agent incompetence
3. [Earned Autonomy](https://crbazevedo.github.io/governed/theory/principles/) -- Trust evolves through observed outcomes
4. [Bounded Blast Radius](https://crbazevedo.github.io/governed/theory/principles/) -- Constrain maximum damage potential
5. [Graceful Degradation](https://crbazevedo.github.io/governed/theory/principles/) -- Narrow scope rather than fail completely
6. [Decision Debt Tracking](https://crbazevedo.github.io/governed/theory/principles/) -- Deferred decisions accumulate risk
7. [Temporal Governance](https://crbazevedo.github.io/governed/theory/principles/) -- Control WHEN, not just WHETHER
8. [Cross-Domain Barriers](https://crbazevedo.github.io/governed/theory/principles/) -- Information barriers between governance domains
9. [Minimal Oversight](https://crbazevedo.github.io/governed/theory/principles/) -- Optimize for least intervention at target quality

## Performance

Full pipeline (5 handlers): **0.022ms p50, 45,000 executions/sec.** Tracing adds zero measurable overhead.

## Links

- [Documentation](https://crbazevedo.github.io/governed/)
- [Examples](examples/) -- 8 runnable examples, no API keys required
- [Theory](https://crbazevedo.github.io/governed/theory/) -- Information-theoretic foundation
- [Comparisons](https://crbazevedo.github.io/governed/comparisons/) -- How it compares to MS Agent Gov Toolkit, Salus, NeMo

## Citation

```bibtex
@software{azevedo2026governed,
  title={governed-agents: Governed Autonomy Middleware for AI Agent Systems},
  author={Azevedo, Carlos R. B.},
  year={2026},
  url={https://github.com/crbazevedo/governed}
}
```

## License

MIT -- Copyright (c) 2026 Carlos R. B. Azevedo
