# Trust & Earned Autonomy

Agents earn trust through observed outcomes, not declarations. The `TrustLedger` records what happened and computes whether an agent deserves more or less autonomy.

This implements [Principle 3: Earned Autonomy](../PRINCIPLES.md#3-earned-autonomy) and enables [Principle 2: Masking Transparency](../PRINCIPLES.md#2-masking-transparency).

## TrustLedger: Recording Outcomes

The `TrustLedger` is the feedback loop that makes governance adaptive. Without it, VT tiers are static configuration. With it, agents move along the trust spectrum based on their track record.

```python
from governed_agents.trust import TrustLedger, Outcome

ledger = TrustLedger(
    min_observations=20,       # Minimum observations before recommending changes
    promote_threshold=0.85,    # sigma_raw above this -> recommend lower VT
    demote_threshold=0.50,     # sigma_raw below this -> recommend higher VT
    decay_rate=0.01,           # Per-observation decay for old evidence
    max_vt_change_per_period=1,  # Max one VT level change per evaluation
)

# Record outcomes as they happen
ledger.record(Outcome(
    action="send_email",
    agent_id="assistant",
    verdict="allow",
    human_decision="approved",
    succeeded=True,
))
```

Each `Outcome` captures:

| Field | Type | Meaning |
|-------|------|---------|
| `action` | `str` | What action was taken |
| `agent_id` | `str` | Which agent took it |
| `verdict` | `str` | Pipeline verdict: "allow", "block", "modify" |
| `human_decision` | `str` | "approved", "rejected", "edited", "ignored", or "" |
| `succeeded` | `bool | None` | Did the action succeed? `None` = unknown |

## How sigma_raw Is Computed

The competence estimate uses exponentially weighted observations:

1. Each observation gets a weight: `(1 - decay_rate) ^ age`, where `age` is how many observations ago it was recorded.
2. Recent observations carry more weight than old ones.
3. For **sigma_raw** (raw competence): `succeeded=True` or `human_decision="approved"` count as success. `human_decision="edited"` counts as failure -- the human had to fix it.
4. For **sigma_corr** (corrected quality): `succeeded=True` or `human_decision="approved"` count as success, regardless of whether the human edited the output.
5. The **masking index** M* = sigma_corr / sigma_raw. When M* > 1.3, human correction is hiding agent weakness.

```python
signal = ledger.signal("assistant", "send_email")
print(signal.sigma_raw)         # 0.82 -- raw agent competence
print(signal.sigma_corr)        # 0.95 -- quality after human correction
print(signal.masking_index)     # 1.16 -- acceptable masking
print(signal.observation_count) # 45
print(signal.recommended_vt)    # 1 (recommending VT1)
```

!!! warning "Masking alerts"
    When `masking_index > 1.3`, the human is compensating for 30%+ of agent failures. Use `ledger.masking_alerts` to find all (agent, action) pairs with excessive masking.

## VT Transitions

The ledger recommends VT transitions based on accumulated evidence:

```python
recommendation = ledger.recommend("assistant", "send_email", current_vt=2)

if recommendation:
    print(recommendation.direction)       # "promote"
    print(recommendation.recommended_vt)  # 1
    print(recommendation.confidence)      # 0.75
    print(recommendation.evidence_count)  # 45
    print(recommendation.reason)
    # "sigma_raw=0.82 over 45 observations. Promoting: VT2 -> VT1"
```

### Evidence gates

- Minimum `min_observations` (default: 20) before any recommendation.
- `sigma_raw >= promote_threshold` (0.85) to recommend lowering VT (more trust).
- `sigma_raw <= demote_threshold` (0.50) to recommend raising VT (less trust).

### Monotonic constraints

- Maximum one VT level change per evaluation period (`max_vt_change_per_period=1`).
- No skipping from VT3 to VT0. An agent must earn each level sequentially.
- One incident (`record_incident()`) demotes one level, not to VT4.

### sigma_raw to VT mapping

| sigma_raw | Recommended VT | Meaning |
|-----------|----------------|---------|
| >= 0.90 | VT0 | Highly competent |
| >= 0.75 | VT1 | Competent with logging |
| >= 0.55 | VT2 | Moderate, needs approval |
| >= 0.35 | VT3 | Low, advisory only |
| < 0.35 | VT4 | Incompetent, block |

## TrustEvolutionHandler in the Pipeline

The `TrustEvolutionHandler` connects the ledger to the pipeline. Place it **before** `VTGovernanceHandler`:

```python
from governed_agents import GovernancePipeline, VTGovernanceHandler
from governed_agents.trust import TrustLedger, TrustEvolutionHandler

ledger = TrustLedger()
# ... record outcomes over time ...

pipeline = GovernancePipeline()
pipeline.add(TrustEvolutionHandler(ledger, vt_floors={"deploy": 2}))  # Adjusts VT
pipeline.add(VTGovernanceHandler())  # Enforces VT

# Now execute: the pipeline may MODIFY vt_tier based on trust evidence
result = await pipeline.execute(ctx)
```

The handler:

1. Looks up the trust signal for the (agent_id, action) pair.
2. If sufficient evidence exists, recommends a VT transition.
3. Returns `MODIFY` with the adjusted `vt_tier` in the context.
4. Respects `vt_floors` -- a floor of VT2 for "deploy" means trust can never lower it below VT2.

When trust adjusts the VT tier, the modified context's metadata includes:

- `trust_sigma_raw`, `trust_sigma_corr`, `trust_masking` -- the trust signals
- `trust_observations` -- evidence count
- `trust_original_vt` -- what the VT was before adjustment
- `trust_transition` -- "promote" or "demote"

## Masking Detection and Alerts

```python
# Get all (agent, action) pairs with excessive masking
alerts = ledger.masking_alerts

for signal in alerts:
    print(f"ALERT: {signal.agent_id}/{signal.action}")
    print(f"  Raw competence: {signal.sigma_raw}")
    print(f"  Corrected quality: {signal.sigma_corr}")
    print(f"  Masking index: {signal.masking_index}")
    print(f"  Observations: {signal.observation_count}")
```

Masking alerts fire when:

- `masking_index > 1.3` (human compensating for 30%+ of failures)
- `observation_count >= 10` (enough data to be meaningful)

Use this to identify agents that appear competent but depend on human correction to maintain quality.
