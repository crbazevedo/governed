# Advanced

This page covers features for complex governance scenarios: temporal windows, decision debt, domain barriers, and AMO integration.

## Action Opportunity Windows (AOW)

AOW windows control *when* actions can happen, not just *whether* they can. An action that's safe at 2 PM may not be safe at 2 AM.

This implements [Principle 6: Temporal Governance](../PRINCIPLES.md#6-temporal-governance).

### Creating a Window

```python
from governed_agents.aow import AOWWindow, AOWState
from datetime import datetime, timedelta, timezone

window = AOWWindow(
    action_id="deploy",
    earliest=datetime.now(timezone.utc),
    optimal=datetime.now(timezone.utc) + timedelta(hours=1),
    latest=datetime.now(timezone.utc) + timedelta(hours=4),
    expiry_warning_minutes=30,
)
```

### Window Lifecycle

```
PENDING --> OPEN --> OPTIMAL --> EXPIRING --> EXPIRED
                                    |
                                    +--> COMPLETED (if action taken)
BLOCKED (external dependency not met)
```

| State | Meaning |
|-------|---------|
| `PENDING` | Before `earliest` -- action not yet available |
| `OPEN` | Within window, action can proceed |
| `OPTIMAL` | Within 30 minutes of `optimal` time |
| `EXPIRING` | Within `expiry_warning_minutes` of `latest` |
| `EXPIRED` | Past `latest` -- terminal state, latched |
| `COMPLETED` | Action was taken -- terminal state, latched |
| `BLOCKED` | Blocked by dependencies |

Terminal states are latched: once expired or completed, the window cannot revert.

```python
state = window.evaluate()  # Returns current AOWState

if state == AOWState.OPEN:
    # Execute the action
    window.mark_completed()
elif state == AOWState.EXPIRING:
    # Warn: window closing soon
    pass
elif state == AOWState.EXPIRED:
    # Too late -- need a new window
    pass
```

### Dependencies

Windows can depend on other actions completing first:

```python
window = AOWWindow(
    action_id="deploy_production",
    earliest=datetime.now(timezone.utc),
    latest=datetime.now(timezone.utc) + timedelta(hours=2),
    blocked_by=["run_tests", "approve_release"],
)

# State will be BLOCKED until blockers are removed
window.remove_blocker("run_tests")
window.remove_blocker("approve_release")
# Now state evaluates based on temporal boundaries
```

### AOWHandler in the Pipeline

```python
from governed_agents.aow import AOWHandler, AOWWindow

handler = AOWHandler()
pipeline.add(handler)

# Pass windows via context metadata
ctx = ActionContext(
    action="deploy",
    agent_id="deployer",
    vt_tier=1,
    metadata={
        "aow_windows": {
            "deploy": window,
        },
    },
)

result = await pipeline.execute(ctx)
```

When blocked, the handler provides recovery guidance:

- **PENDING:** `RETRY_AFTER_DELAY` with `opens_at` in context
- **EXPIRED:** `DELEGATE_TO_HUMAN` -- request a new window
- **BLOCKED:** `RETRY_AFTER_DELAY` with `blocked_by` list

---

## Decision Debt Tracking

When a human defers a VT2+ decision, it enters the Decision Debt ledger. Deferred decisions accumulate risk: after N deferrals or approaching deadline, they auto-escalate.

This implements [Principle 8: Decision Accountability](../PRINCIPLES.md#8-decision-accountability).

### Creating Decision Debt

```python
from governed_agents.decision_debt import DecisionDebt, DecisionDebtLedger, DebtState

debt = DecisionDebt(
    debt_id="D001",
    action="deploy",
    agent_id="eng",
    vt_tier=2,
    summary="Deploy v2.3 to production",
    max_deferrals=3,
    escalation_threshold=0.5,  # Escalate at 50% of deadline
)
```

### Deferral and Escalation

```python
debt.defer("Not ready yet")   # deferral_count=1, state=DEFERRED
debt.defer("Still reviewing")  # deferral_count=2
debt.defer("Later")            # deferral_count=3 -> state=ESCALATED (auto)
```

Escalation triggers when:

- `deferral_count >= max_deferrals` (default: 3), or
- Deadline proximity exceeds `escalation_threshold` (default: 50% elapsed)

### Risk Score

Each debt item has a risk score from 0.0 to 1.0:

```python
score = debt.risk_score()
# 0.0-0.5 from deferral count (proportional to max_deferrals)
# 0.0-0.5 from deadline proximity (proportional to elapsed time)
```

### Decision Debt Ledger

```python
ledger = DecisionDebtLedger()
ledger.add(debt)

# Track deferrals
ledger.defer("D001", "Not ready")

# Get all unresolved debts
pending = ledger.pending

# Get debts that should be escalated
escalation_candidates = ledger.escalation_candidates

# Aggregate risk
total_risk = ledger.total_risk()  # Average risk across pending debts

# Resolve
ledger.resolve("D001", "Approved by CTO")
```

### Lifecycle States

| State | Meaning |
|-------|---------|
| `PENDING` | Awaiting first decision |
| `DEFERRED` | Human chose to defer |
| `REMINDED` | System sent a reminder |
| `REASSESSED` | Decision was re-evaluated |
| `RESOLVED` | Decision was made |
| `ABORTED` | Action no longer relevant |
| `ESCALATED` | Auto-escalated due to risk |

---

## Domain Barriers (BYOPA)

BYOPA (Bring Your Own Personal Agent) enables the same governance library to enforce different policies in different domains, with information barriers preventing content leakage.

This implements [Principle 7: Domain Isolation](../PRINCIPLES.md#7-domain-isolation).

### Setting Up Domains

```python
from governed_agents.domain import GovernanceProfile, DomainBarrierHandler

personal = GovernanceProfile(
    domain="personal",
    default_vt=1,
    vt_floor={"send_email": 1},
)

corporate = GovernanceProfile(
    domain="corporate",
    default_vt=2,
    vt_floor={"send_email": 2, "deploy": 3},
    blocked_tools={"personal_calendar", "health_records"},
    pii_sensitivity=2,
    audit_required=True,
)

barrier = DomainBarrierHandler(profiles={
    "personal": personal,
    "corporate": corporate,
})
pipeline.add(barrier)
```

### VT Floor Enforcement

Within a domain, the barrier enforces VT floors:

```python
ctx = ActionContext(
    action="send_email",
    agent_id="assistant",
    vt_tier=1,  # Agent requests VT1
    metadata={"domain_scope": "corporate"},
)

result = await pipeline.execute(ctx)
# The barrier MODIFIES vt_tier to 2 (corporate floor for send_email)
```

### Cross-Domain Information Barriers

When an action targets a different domain, the barrier strips content fields. Only structural metadata crosses the boundary:

```python
ctx = ActionContext(
    action="summarize",
    agent_id="assistant",
    vt_tier=1,
    payload={
        "content": "Q3 revenue was $4.2M...",  # Stripped
        "urgency": "high",                      # Passes through
        "timestamp": "2026-01-15",              # Passes through
    },
    metadata={
        "domain_scope": "corporate",
        "target_domain": "personal",
    },
)

result = await pipeline.execute(ctx)
# result.action == Verdict.MODIFY
# Modified payload: {"urgency": "high", "timestamp": "2026-01-15"}
# "content" field was stripped at the domain boundary
```

Allowed cross-domain fields (default): `timestamp`, `duration_minutes`, `urgency`, `domain_scope`, `action_type`. Customizable via `allowed_fields` parameter.

---

## AMO Integration (Optional)

The Axiom of Minimal Oversight (AMO) replaces static VT tier assignment with information-theoretic authority allocation. Instead of hardcoding "this action is VT2," the AMO computes the optimal oversight level based on measured agent competence.

```bash
pip install governed-agents[amo]
```

```python
from governed_agents._amo import DynamicVTHandler

pipeline = GovernancePipeline()
pipeline.add(DynamicVTHandler(p_min=0.80))  # Before VTGovernanceHandler
pipeline.add(VTGovernanceHandler())

ctx = ActionContext(
    action="deploy",
    agent_id="eng",
    vt_tier=2,
    metadata={
        "sigma_skill": 0.82,   # Agent competence (0-1)
        "catch_rate": 0.70,    # Corrector catch probability (0-1)
    },
)

result = await pipeline.execute(ctx)
# AMO may adjust VT2 -> VT1 if the agent's competence warrants it
```

### How AMO Maps to VT Tiers

The AMO computes a continuous authority allocation (0-1), discretized into VT tiers:

| Authority | VT Tier | Meaning |
|-----------|---------|---------|
| >= 0.80 | VT0 | Highly competent, autonomous |
| >= 0.50 | VT1 | Moderate competence, light oversight |
| >= 0.20 | VT2 | Needs review |
| >= 0.05 | VT3 | Low competence, advisory only |
| < 0.05 | VT4 | Agent should not act here |

### Fallback Behavior

When `minimal-oversight` is not installed, `DynamicVTHandler` either:

- Preserves the original VT tier (default), or
- Uses a configurable fallback tier: `DynamicVTHandler(fallback_tier=2)`

### Metadata Output

When AMO adjusts the VT tier, it writes diagnostic metadata:

- `amo_original_vt` -- what the VT was before adjustment
- `amo_optimized_vt` -- what the AMO recommends
- `amo_authority` -- continuous authority value (0-1)
- `amo_capacity` -- operational capacity from the AMO analysis
- `amo_buffer` -- effective autonomy buffer
- `amo_feasible` -- whether the AMO found a feasible solution

See [Theory](../theory.md) for the mathematical connection between AMO and the library.
