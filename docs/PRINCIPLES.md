# Principles of Principled Governance

> Governance is a signal processing problem, not a rule enforcement problem.

These nine principles define what `governed-agents` is and how it should evolve.
Every feature must advance at least one principle. No feature may violate any.

---

## 1. Calibrated Autonomy

**Oversight intensity must match information-theoretic cost, not intuitive fear.**

Over-monitoring strong agents wastes review budget. Under-monitoring weak agents
wastes delegation capacity. The AMO water-filling solution (Eq. 8) proves that
optimal authority follows the Fisher geometry: concentrate review where the
marginal signal per unit of oversight cost is highest.

*Implication:* VT tiers should be continuously adjusted from observed outcomes,
not statically configured. A CalibrationEngine consumes outcome data and moves
agents along the trust spectrum based on evidence, not policy documents.

*Example:* A code-review agent starts at VT2. After 50 reviews with 95% accuracy,
the system moves it to VT1. If accuracy drops to 70%, it moves back. The SQL
agent stays at VT2 regardless — the blast radius floor overrides the trust signal.

---

## 2. Masking Transparency

**Separately track raw competence and corrected quality. Alert when the gap widens.**

Correction creates the illusion of competence. When M* = sigma_corr / sigma_raw
exceeds 1.3, the human reviewer is compensating for 30%+ of agent failures.
Without separate tracking, you optimize for the corrected signal and miss the
degradation underneath.

*Implication:* The audit system must track pre-review and post-review outcomes.
A MaskingMonitor computes M* over sliding windows and alerts when masking rises.

*Example:* A support agent shows 98% satisfaction (sigma_corr = 0.98). But the
human rewrites 40% of responses (sigma_raw = 0.58, M* = 1.69). Without masking
transparency, you conclude it's ready for VT0. With it, you see it would fail.

---

## 3. Earned Autonomy

**Trust accumulates through observed outcomes over volume, not by declaration.**

The Return Operator (Eq. 4) models how competence estimates converge through
repeated observation and decay without fresh evidence. This is Bayesian updating
applied to delegation: belief approaches truth as evidence accumulates.

*Implication:* A TrustLedger records (action, outcome, decision) tuples and
computes rolling sigma_raw. VT transitions require minimum evidence counts and
are monotonically constrained: one level per evaluation period. No skipping
from VT3 to VT0.

*Example:* A deployment agent starts at VT3 (advise only). After 30 accepted
advisories → VT2. After 50 approved proposals that succeeded → VT1. After 100+
observations with <2% failure → VT0. One incident resets one level, not to zero.

---

## 4. Bounded Blast Radius

**Every delegated action must have pre-declared boundaries on maximum damage.**

The autonomy buffer (Eq. 16) only exists when capacity exceeds the quality
target. Budget constraints, rate limits, and scope restrictions increase
the buffer by capping the downside of any single failure.

*Implication:* A BlastRadiusPolicy combines cost, rate, scope, and
irreversibility into a single multi-dimension constraint. Declarable in TOML.

*Example:* A finance agent: max $500/transaction, max $2000/day, max
10 transactions/hour, no wire transfers (irreversibility ceiling).
Expense reports under $500 → VT0. $5000 invoice → VT2. Wire transfer → VT4.

---

## 5. Graceful Degradation

**When governance blocks an action, provide structured recovery paths.**

The AMO scope selection shows that partial delegation at high quality beats
full delegation at low quality. When an action is blocked, the agent should
receive actionable guidance: what to try instead, not just why it was stopped.

*Implication:* GovernanceResult carries a RecoveryAction enum:
RETRY_WITH_APPROVAL, RETRY_LOWER_SCOPE, RETRY_AFTER_DELAY,
DELEGATE_TO_HUMAN, DOWNGRADE_TO_ADVISORY, BATCH_WITH_OTHERS.
Agent frameworks can build programmatic recovery loops.

*Example:* Agent tries bulk email (100 recipients). Rate limiter blocks at
10/minute. Recovery: BATCH_WITH_OTHERS — "chunk into 10 groups of 10,
send at 1-minute intervals." The agent retries with a chunked approach.

---

## 6. Temporal Governance

**Control WHEN actions happen, not just WHETHER they can.**

T*_auto = B_eff / mu_eff (Eq. 17) proves there is a finite window for safe
autonomous operation before drift erodes the quality buffer. After T*_auto,
intervention is mandatory regardless of risk tier.

*Implication:* AOW windows should be auto-generated from autonomy time
estimates. Expired windows create Decision Debt entries. Temporal governance
connects the pipeline to the clock.

*Example:* A content moderation agent has a 6-hour autonomy buffer. At hour 0,
the AOW opens. At hour 4.5 (75% of T*_auto), EXPIRING state triggers a
spot-check reminder. At hour 6, the window expires and reviews require VT2
until a human resets the window.

---

## 7. Domain Isolation

**Information must not leak between governance domains.**

Upstream quality propagates downstream (Eq. 7). If a domain with lower
standards feeds into one with higher standards, the effective quality of
the downstream domain is contaminated. This is the Chinese wall principle
applied to agent systems.

*Implication:* A DomainContextManager provides session-level isolation.
Trust scores, budgets, and rate limits are scoped per domain. Content
is stripped at domain boundaries; only structural metadata crosses.

*Example:* An executive's AI handles personal finances and corporate
strategy. When switching domains, the barrier strips personal financial
data. Trust for "draft email" is tracked separately: VT0 personal, VT2
corporate.

---

## 8. Decision Accountability

**Every governance decision is traceable. Deferred decisions accumulate risk.**

Governance failures are only detectable by tracking joint metric trajectories
over time. A single snapshot tells you nothing. Decision Debt formalizes
the cost of inaction: risk compounds monotonically, forcing resolution.

*Implication:* Every BLOCK auto-creates a DecisionDebt entry if not retried
within a configurable window. Execution traces are persistable for audit.
GovernanceReport aggregates health metrics.

*Example:* A PR approval request goes unanswered for 30 minutes. DecisionDebt
records deferral #1. After 3 deferrals → auto-escalate to the next approver.
After 6 hours unresolved → Slack alert to team lead. Full chain is auditable.

---

## 9. Minimum Viable Governance

**Every rule must reduce risk more than it reduces capacity.**

H_crit = (C_op - p_min) / lambda proves there is a hard ceiling on governance
complexity. Above it, the process overhead alone exceeds available capacity.
More governance can make the system LESS safe by pushing it past the
capacity cliff.

*Implication:* A GovernanceOverheadMonitor tracks pipeline execution entropy
and warns when overhead approaches H_crit. The three-layer architecture
(static/dynamic/persistent) lets users adopt only what they need.
Adding handlers must be justified by marginal safety contribution.

*Example:* A team has 12 handlers. The monitor shows 85% of H_crit and
warns. They discover two custom validators overlap and remove one, dropping
to 72%. The system becomes MORE safe by having LESS governance.

---

## The Meta-Principle

> Governance is a signal processing problem, not a rule enforcement problem.

Rules are static. Signals are dynamic. The library's job is to:

1. **Measure** the signal (competence, masking, drift, decision debt)
2. **Compute** the optimal response (calibrated VT, blast radius, temporal window)
3. **Surface** the residual uncertainty to humans (structured recovery, accountability)

Everything else is infrastructure that belongs to the consumer.
