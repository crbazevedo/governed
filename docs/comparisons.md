# Comparisons

An honest assessment. We don't oversell. We acknowledge where others are better. We're bold about what's genuinely ours.

## The Market

The AI agent governance space has three layers:

```
Layer 3: Observability & Compliance    <-- Openlayer, Galileo, LangSmith
Layer 2: Runtime Action Governance     <-- governed-agents, MS Toolkit, Salus
Layer 1: I/O Content Guardrails        <-- NeMo Guardrails, Guardrails AI, OpenAI SDK
```

Most products operate at Layer 1 (what the LLM says) or Layer 3 (what went wrong). Layer 2 (what the agent *does*) is where `governed-agents` lives.

## Comparison Table

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
| Multi-language support | No (Python) | Yes (5 langs) | No | No |
| Enterprise compliance automation | No | Yes | No | No |
| Cryptographic agent identity | No | Yes | No | No |

## Direct Competitors

### Microsoft Agent Governance Toolkit (April 2026)

**They're ahead on:** Enterprise scale, framework breadth (7+ frameworks), sub-ms latency, OWASP coverage, multi-language support, cryptographic agent identity, compliance automation (EU AI Act, HIPAA, SOC2).

**We're ahead on:** The governance *model*. Microsoft's toolkit is a policy engine -- it evaluates rules against actions. `governed-agents` is an autonomy calibration system -- it determines how much freedom to grant based on risk, time, cognitive load, and domain context.

**Honest take:** If you need enterprise runtime security for a fleet of agents, use Microsoft's toolkit. If you need principled autonomy delegation for agents that earn trust over time, `governed-agents` offers concepts Microsoft doesn't have (VT tiers, AOW, Decision Debt, BYOPA).

### Salus (YC W26, $3.7M)

**They're ahead on:** Policy definition UX (YAML/markdown/English), self-repair on blocked actions (58% recovery rate), evidence grounding (validates actions against prior tool call data).

**We're ahead on:** Self-hosted ownership (Salus is SaaS -- you send your agent's actions to their API), the governance model (they block bad actions; we calibrate autonomy levels), and BYOPA compatibility (a SaaS governance layer contradicts the "bring your own agent" philosophy).

**Honest take:** Salus's self-repair loop is genuinely better than our binary block/allow. We should learn from their structured feedback pattern. But for governance you *own* and control locally, they're a philosophical mismatch.

## Adjacent Products (Different Layer)

### NeMo Guardrails (NVIDIA)

Governs what the LLM **says** (topic control, jailbreak prevention). We govern what the agent **does** (tool calls, actions, decisions). **Complementary.** Use NeMo for I/O safety and governed-agents for action governance.

### Guardrails AI

I/O validation (is this output well-formed?). We do pre-execution policy (should this action proceed?). Different problem.

### LangGraph

Best-in-class HITL plumbing (pause, persist state, resume with approve/edit/reject). We should integrate with LangGraph's HITL, not compete with it. Our VT model + their state management = powerful combination.

### CrewAI

Task-output validation guardrails. Post-task, not pre-action. Different layer.

## What's Genuinely Ours

These concepts exist in no other governance product:

| Concept | What It Is | Why It Matters |
|---------|-----------|----------------|
| **VT0-VT4 Risk Tiers** | 5 behavior modes from autonomous to blocked, tied to action classification | Other systems have allow/deny. We have a graduated trust spectrum that agents can move along. |
| **Action Opportunity Windows** | Time-bounded windows with PENDING->OPEN->EXPIRING->EXPIRED lifecycle | No other system connects governance to TIME. An action that's safe at 2 PM may not be safe at 2 AM. |
| **Decision Debt** | Deferred decisions tracked as accumulating risk with auto-escalation | The concept that NOT deciding is itself a risk. 3 deferrals or 50% deadline elapsed triggers forced escalation. |
| **BYOPA Domain Barriers** | Personal/corporate information barriers with metadata-only cross-domain correlation | Nobody else bridges personal and corporate AI governance. |
| **Interface-First Architecture** | Governance LOGIC is ours, governance INFRASTRUCTURE is pluggable | Most governance tools bundle their own PII/audit/rate-limit implementations. We define interfaces and let you plug in what you already use. |

## When to Use governed-agents

**Use us when:**

- You need graduated autonomy, not binary allow/deny
- Agents should earn trust through observed outcomes
- You need temporal governance (when, not just whether)
- You need cross-domain isolation (personal/corporate)
- You want to own and run your governance locally
- You have existing infrastructure (Presidio, Redis, litellm) to plug in

**Use something else when:**

- You need enterprise compliance automation today (Microsoft)
- You need multi-language support today (Microsoft)
- You need I/O content guardrails (NeMo, Guardrails AI)
- You prefer SaaS over self-hosted (Salus)
- You need HITL workflow orchestration, not governance policy (LangGraph)

## Complementary Tools

`governed-agents` is middleware. It governs the decision layer. These tools complement it:

| Tool | Complements How |
|------|----------------|
| **NeMo Guardrails** | I/O safety (what the LLM says) + governed-agents (what the agent does) |
| **LangGraph** | HITL state management (pause/resume) + governed-agents (when to pause) |
| **Presidio** | PII detection backend for PIIFilter |
| **litellm** | Cost tracking backend for BudgetGatekeeper |
| **Redis** | Rate limiting, audit, and persistence backends |
