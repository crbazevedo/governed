# Competitive Landscape: AI Agent Governance (April 2026)

> Honest assessment. We don't oversell. We acknowledge where others are better.
> We're bold about what's genuinely ours.

## The Market

The AI agent governance space has three layers, each with different players:

```
Layer 3: Observability & Compliance    ← Openlayer, Galileo, LangSmith
Layer 2: Runtime Action Governance     ← governed-agents, MS Toolkit, Salus
Layer 1: I/O Content Guardrails        ← NeMo Guardrails, Guardrails AI, OpenAI SDK
```

Most products operate at Layer 1 (what the LLM says) or Layer 3 (what went wrong).
Layer 2 (what the agent DOES) is where `governed-agents` lives.

## Direct Competitors

### Microsoft Agent Governance Toolkit (April 2, 2026)

**They're ahead on:** Enterprise scale, framework breadth (7+), sub-ms latency,
OWASP coverage, multi-language support, cryptographic agent identity, compliance
automation (EU AI Act, HIPAA, SOC2).

**We're ahead on:** The governance MODEL. Microsoft's toolkit is a policy engine —
it evaluates rules against actions. `governed-agents` is an autonomy calibration
system — it determines how much freedom to grant based on risk, time, cognitive
load, and domain context.

**Honest take:** If you need enterprise runtime security for a fleet of agents,
use Microsoft's toolkit. If you need principled autonomy delegation for agents
that earn trust over time, `governed-agents` offers concepts Microsoft doesn't
have (VT tiers, AOW, Decision Debt, BYOPA).

### Salus (YC W26, $3.7M)

**They're ahead on:** Policy definition UX (YAML/markdown/English), self-repair
on blocked actions (58% recovery rate), evidence grounding (validates actions
against prior tool call data).

**We're ahead on:** Self-hosted ownership (Salus is SaaS — you send your agent's
actions to their API), the governance model (they block bad actions; we calibrate
autonomy levels), and BYOPA compatibility (a SaaS governance layer contradicts
the "bring your own agent" philosophy).

**Honest take:** Salus's self-repair loop is genuinely better than our binary
block/allow. We should learn from their structured feedback pattern. But for
governance you OWN and control locally, they're a philosophical mismatch.

## Adjacent Products (Different Layer)

### NeMo Guardrails (NVIDIA)

Governs what the LLM **says** (topic control, jailbreak prevention). We govern
what the agent **does** (tool calls, actions, decisions). Complementary.

### Guardrails AI

I/O validation (is this output well-formed?). We do pre-execution policy
(should this action proceed?). Different problem.

### LangGraph

Best-in-class HITL plumbing (pause, persist state, resume with approve/edit/reject).
We should integrate with LangGraph's HITL, not compete with it. Our VT model +
their state management = powerful combination.

### CrewAI

Task-output validation guardrails. Post-task, not pre-action. Different layer.

## What's Genuinely Ours (Exists Nowhere Else)

| Concept | What It Is | Why It Matters |
|---------|-----------|----------------|
| **VT0-VT4 Risk Tiers** | 5 behavior modes from autonomous to blocked, tied to action classification | Other systems have allow/deny. We have a graduated trust spectrum that agents can move along. |
| **Action Opportunity Windows** | Time-bounded windows for when actions can happen, with PENDING→OPEN→EXPIRING→EXPIRED lifecycle | No other system connects governance to TIME. An action that's safe at 2 PM may not be safe at 2 AM. |
| **Decision Debt** | Deferred decisions tracked as accumulating risk with auto-escalation at thresholds | The concept that NOT deciding is itself a risk. 3 deferrals or 50% deadline elapsed → forced escalation. |
| **BYOPA Domain Barriers** | Personal/corporate information barriers with metadata-only cross-domain correlation | Nobody else bridges personal and corporate AI governance. This is the "killer app" for governed personal agents. |
| **Interface-First Architecture** | Governance LOGIC is ours, governance INFRASTRUCTURE is pluggable | Most governance tools bundle their own PII/audit/rate-limit implementations. We define interfaces and let you plug in Presidio, litellm, Redis, whatever you already use. |

## What We Don't Have (And That's OK)

| Feature | Who Has It | Why We Don't Need It (Yet) |
|---------|-----------|---------------------------|
| Multi-language support | MS Toolkit (5 langs) | Python-first is correct for v1. The AI agent ecosystem is Python-dominant. |
| Sub-ms latency guarantee | MS Toolkit | We haven't benchmarked. Need to before claiming performance. |
| Compliance report generation | MS Toolkit, Openlayer | Enterprise feature. Build when enterprise users ask for it. |
| Cryptographic agent identity | MS Toolkit | Zero-trust is enterprise infrastructure. Not relevant for personal agents. |
| ML-based PII detection | NeMo, Presidio | We provide the `PIIDetector` interface. Plug in Presidio. Don't rebuild NLP. |
| Self-repair on rejection | Salus | Good idea. Should add structured feedback to `GovernanceResult` in v0.2. |
| OWASP Agentic AI coverage | MS Toolkit | Marketing metric. Our VT model addresses the risks; we just don't map to the checklist. |

## What We Should Add (Gaps Worth Closing)

| Gap | Priority | Why |
|-----|----------|-----|
| **Structured rejection feedback** | HIGH | Salus's self-repair shows blocked actions can recover with feedback. Our `GovernanceResult.abort()` should include a `suggestion` field. |
| **YAML policy definition** | HIGH | Python-code handlers are powerful but high-friction. A YAML governance profile would lower adoption barriers. |
| **Approve/edit/reject HITL** | MEDIUM | LangGraph supports "edit" as a middle ground. Our binary approve/reject misses this. |
| **Pipeline performance benchmarks** | MEDIUM | Can't claim "lightweight" without numbers. Benchmark before launch. |
| **EU AI Act Article 14 mapping** | LOW | Document how VT tiers satisfy the human oversight requirement. Marketing, not code. |

## Positioning

**What we say:**

> `governed-agents` is a Python library for principled autonomy delegation
> in AI agent systems. It provides the governance MODEL — risk-tiered
> authorization, temporal action windows, decision debt tracking, and
> cross-domain information barriers — while letting you plug in your own
> infrastructure for PII detection, cost tracking, audit logging, and
> human approval routing.

**What we don't say:**

We don't say we're a complete governance platform. We don't say we replace
Microsoft's toolkit or NeMo Guardrails. We say: those tools govern what
agents CAN do. We govern how much they SHOULD do, and when, and for how long.

**The one-line pitch:**

> Other tools set guardrails. We calibrate autonomy.

## Theoretical Foundation

Unlike any competitor, `governed-agents` has a published theoretical basis:

> Azevedo, C.R.B. (2026). "Minimal Oversight: A Theory of Principled
> Autonomy Delegation." arXiv:submit/7429273.

The paper derives the governance model from information-theoretic first
principles (Fisher information, variational optimization). The VT tier
model implements the paper's authorization field. The AMO (Axiom of
Minimal Oversight) provides the mathematical foundation for optimal
oversight allocation. No other governance library has a theoretical basis.

This is available as an optional integration: `pip install governed-agents[amo]`
imports `minimal-oversight` for dynamic, AMO-driven VT assignment.
