# Blast Radius

The `BlastRadiusPolicy` combines cost, frequency, scope, and irreversibility constraints into a single declaration that bounds the maximum damage an agent can cause.

This implements [Principle 4: Bounded Blast Radius](../PRINCIPLES.md#4-bounded-blast-radius).

## The Problem

Configuring `BudgetGatekeeper` + `RateLimiter` + scope checks separately works, but each dimension is evaluated independently. A finance agent might pass the budget check ($400 < $500 limit) and the rate check (8 < 10/hour), but the *combination* of 8 transactions at $400 each ($3,200) far exceeds the daily budget.

`BlastRadiusPolicy` evaluates all dimensions in one pass. One declaration, one handler, unified constraint enforcement.

## BlastRadiusPolicy

```python
from governed_agents.blast_radius import BlastRadiusPolicy, BlastRadiusHandler

policy = BlastRadiusPolicy(
    # Cost constraints
    max_cost_per_action=500.0,      # No single action over $500
    max_cost_per_hour=2000.0,       # Hourly cost ceiling
    max_cost_per_day=5000.0,        # Daily cost ceiling

    # Frequency constraints
    max_actions_per_hour=10,        # Max 10 actions per hour
    max_actions_per_day=100,        # Max 100 actions per day

    # Irreversibility constraints
    max_irreversible_per_day=0,     # No irreversible actions allowed
    irreversible_actions=frozenset({"wire_transfer", "delete_account"}),

    # Scope constraints
    scope_ceiling="staging",        # Max allowed scope
    blocked_scopes=frozenset({"production"}),

    # High-risk action elevation
    high_risk_actions=frozenset({"deploy", "delete_data"}),
    high_risk_vt=3,                 # Elevate to VT3
)

handler = BlastRadiusHandler(policy)
pipeline.add(handler)
```

All fields are optional. Only set the constraints you care about.

## Irreversibility Classification

Actions are classified as irreversible by listing them in `irreversible_actions`. The handler enforces a daily limit (`max_irreversible_per_day`). Setting this to 0 blocks all irreversible actions.

```python
policy = BlastRadiusPolicy(
    irreversible_actions=frozenset({
        "wire_transfer",
        "delete_account",
        "revoke_access",
        "publish_to_production",
    }),
    max_irreversible_per_day=2,  # Allow up to 2 per day
)
```

When an irreversible action is blocked, the recovery plan includes `DELEGATE_TO_HUMAN`:

```python
result = await pipeline.execute(ctx)
# result.recovery.primary == RecoveryAction.DELEGATE_TO_HUMAN
```

## High-Risk Action Elevation

Actions listed in `high_risk_actions` are automatically elevated to a higher VT tier:

```python
policy = BlastRadiusPolicy(
    high_risk_actions=frozenset({"deploy", "modify_permissions"}),
    high_risk_vt=2,  # Elevate to VT2 (require approval)
)
```

If the action's current VT tier is below `high_risk_vt`, the handler returns `MODIFY` with the elevated tier. The downstream `VTGovernanceHandler` then enforces the elevated tier.

## Cost Tracking

Pass action cost via `context.metadata["estimated_cost_usd"]`. After execution, call `handler.record_cost()` to track cumulative spend:

```python
ctx = ActionContext(
    action="generate_report",
    agent_id="analyst",
    vt_tier=1,
    metadata={"estimated_cost_usd": 0.15},
)

result = await pipeline.execute(ctx)

if result.action != Verdict.BLOCK:
    # Execute the action, then record actual cost
    handler.record_cost(0.12)
```

## Scope Constraints

The `scope_ceiling` and `blocked_scopes` fields control where actions can operate. Pass the scope via `context.metadata["scope"]`:

```python
ctx = ActionContext(
    action="deploy",
    agent_id="deployer",
    vt_tier=1,
    metadata={"scope": "production"},
)

# Blocked: "production" is in blocked_scopes
result = await pipeline.execute(ctx)
# result.recovery.primary == RecoveryAction.RETRY_LOWER_SCOPE
# result.recovery.context == {"blocked_scope": "production", "max_scope": "staging"}
```

## TOML Configuration

BlastRadiusPolicy can be declared in TOML (loaded via your application's config loader):

```toml
[blast_radius]
max_cost_per_action = 500.0
max_cost_per_hour = 2000.0
max_cost_per_day = 5000.0
max_actions_per_hour = 10
max_actions_per_day = 100
max_irreversible_per_day = 0
irreversible_actions = ["wire_transfer", "delete_account"]
blocked_scopes = ["production"]
scope_ceiling = "staging"
high_risk_actions = ["deploy", "delete_data"]
high_risk_vt = 3
```

!!! note
    The `BlastRadiusHandler` is not yet part of the TOML pipeline loader registry. Use it via code for now. TOML integration is planned for v0.2.

## When to Use BlastRadiusPolicy vs Individual Handlers

| Scenario | Use |
|----------|-----|
| Simple rate limiting only | `RateLimiter` |
| Simple budget only | `BudgetGatekeeper` |
| Multi-dimension constraints (cost + rate + scope + irreversibility) | `BlastRadiusPolicy` |
| Irreversibility classification | `BlastRadiusPolicy` |
| High-risk action elevation | `BlastRadiusPolicy` |

The `BlastRadiusPolicy` replaces all three individual handlers when you need unified constraint evaluation. Use the individual handlers when you only need one dimension.
