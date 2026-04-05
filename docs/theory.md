# Theory

`governed-agents` is the engineering realization of the theoretical framework in:

> Azevedo, C.R.B. (2026). "Minimal Oversight: A Theory of Principled Autonomy Delegation." arXiv:submit/7429273.

No other governance library has a published theoretical basis. This page maps the paper's key equations to their library implementations.

## The Paper in Brief

The paper asks: *given a group of AI agents with different competence levels, how should a resource-constrained human optimally allocate oversight?*

The answer is derived from information-theoretic first principles (Fisher information, variational optimization) and produces:

1. An **optimal authority allocation** (how much freedom each agent gets)
2. An **autonomy time** (how long an agent can operate safely before drift erodes quality)
3. A **masking index** (how much human correction hides agent weakness)
4. A **minimum governance threshold** (the capacity cliff beyond which more rules make things worse)

## Key Equations and Their Library Implementations

### The Return Operator -> TrustLedger

**Paper (Eq. 4):** The Return Operator models how competence estimates converge through repeated Bayesian observation and decay without fresh evidence.

**Library:** `TrustLedger` records `(action, outcome, decision)` tuples and computes rolling `sigma_raw` using exponentially weighted observations. Recent outcomes carry more weight than old ones (decay rate). The competence estimate converges to the agent's true competence as evidence accumulates.

```python
from governed_agents.trust import TrustLedger, Outcome

ledger = TrustLedger(
    min_observations=20,
    promote_threshold=0.85,
    demote_threshold=0.50,
    decay_rate=0.01,
)

# Each observation updates sigma_raw via exponential weighting
ledger.record(Outcome(action="deploy", agent_id="eng", succeeded=True))

signal = ledger.signal("eng", "deploy")
# signal.sigma_raw is the Return Operator's output: a decaying,
# observation-weighted competence estimate
```

**Mapping:**

| Paper Concept | Library Implementation |
|---------------|----------------------|
| sigma (competence estimate) | `TrustSignal.sigma_raw` |
| Observation weight decay | `TrustLedger.decay_rate` |
| Convergence through volume | `TrustSignal.observation_count` |
| Bayesian updating | Exponentially weighted mean over outcomes |

---

### The AMO Water-Filling -> DynamicVTHandler

**Paper (Eq. 8):** The Axiom of Minimal Oversight (AMO) uses a water-filling algorithm to allocate authority across agents. The solution concentrates oversight where the marginal signal per unit of oversight cost is highest -- just as Shannon's water-filling allocates power to channels with the best signal-to-noise ratio.

**Library:** `DynamicVTHandler` builds a pipeline graph from the agent's metadata, runs the AMO analysis, and maps the continuous authority allocation to a discrete VT tier.

```python
from governed_agents._amo import DynamicVTHandler

handler = DynamicVTHandler(p_min=0.80)
pipeline.add(handler)

# Context provides agent competence signals
ctx = ActionContext(
    action="deploy", agent_id="eng", vt_tier=2,
    metadata={"sigma_skill": 0.82, "catch_rate": 0.70},
)

# DynamicVTHandler computes:
# 1. operational capacity (c_op) from sigma_skill and catch_rate
# 2. authority allocation from AMO water-filling
# 3. maps authority to VT tier
```

**Mapping:**

| Paper Concept | Library Implementation |
|---------------|----------------------|
| Authority alpha_i | `DynamicVTHandler._authority_to_vt()` |
| Water-filling solution | `minimal_oversight.analyze_pipeline()` |
| Quality target p_min | `DynamicVTHandler(p_min=...)` |
| Fisher information geometry | Internal to minimal-oversight library |

---

### The Masking Index -> TrustSignal.masking_index

**Paper (Eq. 6):** M* = sigma_corr / sigma_raw. When M* exceeds 1.3, the human reviewer is compensating for 30%+ of agent failures. The corrected quality creates an illusion of competence.

**Library:** `TrustSignal.masking_index` is computed by the `TrustLedger` from separate tracking of raw outcomes (before human correction) and corrected outcomes (after human correction).

```python
signal = ledger.signal("assistant", "send_email")
print(signal.masking_index)  # 1.69 -- human is masking 69% of failures

alerts = ledger.masking_alerts
# All (agent, action) pairs where masking_index > 1.3
```

**Mapping:**

| Paper Concept | Library Implementation |
|---------------|----------------------|
| sigma_raw | `TrustSignal.sigma_raw` |
| sigma_corr | `TrustSignal.sigma_corr` |
| M* (masking index) | `TrustSignal.masking_index` |
| Masking alert threshold | `TrustLedger.masking_alerts` (M* > 1.3) |

---

### Autonomy Time -> AOWWindow

**Paper (Eq. 17):** T*_auto = B_eff / mu_eff. There is a finite window for safe autonomous operation before drift erodes the quality buffer. After T*_auto, intervention is mandatory.

**Library:** `AOWWindow` implements time-bounded action windows with PENDING->OPEN->EXPIRING->EXPIRED lifecycle. The `expiry_warning_minutes` parameter triggers the EXPIRING state before the window closes.

```python
from governed_agents.aow import AOWWindow, AOWState
from datetime import datetime, timedelta, timezone

# T*_auto = 4 hours (computed externally or configured)
window = AOWWindow(
    action_id="moderate_content",
    earliest=datetime.now(timezone.utc),
    latest=datetime.now(timezone.utc) + timedelta(hours=4),
    expiry_warning_minutes=30,
)

state = window.evaluate()
# OPEN -> EXPIRING (at 3.5 hours) -> EXPIRED (at 4 hours)
```

**Mapping:**

| Paper Concept | Library Implementation |
|---------------|----------------------|
| T*_auto (autonomy time) | `AOWWindow.latest - AOWWindow.earliest` |
| B_eff (autonomy buffer) | Computed externally, sets window duration |
| Drift detection | EXPIRING state at `expiry_warning_minutes` |
| Mandatory intervention | EXPIRED state (latched -- cannot revert) |

---

### Effective Autonomy Buffer -> BlastRadiusPolicy

**Paper (Eq. 16):** The effective autonomy buffer B_eff exists when operational capacity exceeds the quality target. Budget constraints, rate limits, and scope restrictions increase B_eff by capping downside risk.

**Library:** `BlastRadiusPolicy` combines cost, rate, scope, and irreversibility constraints into a single declaration. Each constrained dimension increases the effective autonomy buffer.

```python
from governed_agents.blast_radius import BlastRadiusPolicy

policy = BlastRadiusPolicy(
    max_cost_per_action=500.0,
    max_cost_per_day=5000.0,
    max_actions_per_hour=10,
    max_irreversible_per_day=0,
    irreversible_actions=frozenset({"wire_transfer"}),
)
# Each constraint bounds downside risk, increasing B_eff
```

---

### Critical Entropy -> Minimum Viable Governance

**Paper:** H_crit = (C_op - p_min) / lambda. There is a hard ceiling on governance complexity. Above it, overhead exceeds capacity.

**Library:** The three-layer architecture (static/dynamic/persistent) lets users adopt only what they need. The pipeline's 0.022ms p50 latency ensures governance overhead stays well below the capacity cliff for most applications.

This is a design principle rather than a specific class. The library does not (yet) implement an explicit governance overhead monitor, but the principle constrains all design decisions: every handler must justify its existence by reducing more risk than it consumes in overhead.

---

## Optional [amo] Extra

The `minimal-oversight` library provides the full AMO implementation:

```bash
pip install governed-agents[amo]
```

Without it, `governed-agents` uses static VT tiers configured by the developer. With it, `DynamicVTHandler` replaces static assignment with information-theoretic allocation.

The AMO extra is optional because:

1. Static VT tiers are sufficient for most applications
2. The AMO requires competence measurements (`sigma_skill`, `catch_rate`) that not all systems track
3. The theoretical precision matters most in systems with many agents and limited human review capacity

## Citation

```bibtex
@article{azevedo2026minimal,
  title={Minimal Oversight: A Theory of Principled Autonomy Delegation},
  author={Azevedo, Carlos R. B.},
  year={2026},
  note={arXiv:submit/7429273}
}

@software{azevedo2026governed,
  title={governed-agents: Governed Autonomy Middleware for AI Agent Systems},
  author={Azevedo, Carlos R. B.},
  year={2026},
  url={https://github.com/crbazevedo/governed}
}
```
