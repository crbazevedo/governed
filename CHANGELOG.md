# Changelog

All notable changes to governed-agents are documented here.

## [0.1.0] - 2026-04-05

### Added

**Core Pipeline**
- `GovernancePipeline` with priority-grouped, mixed parallel/sequential execution
- `GovernanceHandler` ABC with `evaluate()` protocol
- `ActionContext` and `GovernanceResult` data types
- `Verdict` enum: ALLOW, BLOCK, MODIFY
- `pipeline.add()` auto-priority and `pipeline.register()` explicit priority
- `ExecutionTrace` and `HandlerTrace` for pipeline introspection
- `execute_traced()` for zero-overhead execution tracing

**VT Risk Tiers**
- `VTTier` enum (VT0-VT4) with graduated autonomy semantics
- `VTGovernanceHandler` for static tier enforcement
- Safe default: `vt_tier=1` (log & proceed, not silent bypass)

**Trust & Earned Autonomy**
- `TrustLedger` for recording outcomes and computing rolling sigma_raw
- `TrustEvolutionHandler` for evidence-gated VT tier transitions
- Masking detection (M* alerts when corrected quality hides raw degradation)
- Exponentially weighted competence estimates (Return Operator dynamics)

**Recovery & Graceful Degradation**
- `RecoveryAction` enum (8 typed recovery strategies)
- `RecoveryPlan` dataclass on every BLOCK verdict
- Structured feedback: agents can programmatically inspect and act on recovery

**Blast Radius**
- `BlastRadiusPolicy` for unified multi-dimension constraints
- Cost, frequency, scope, and irreversibility in one declaration
- `BlastRadiusHandler` evaluates all dimensions in a single pass

**Built-in Handlers**
- `PIIFilter` with pluggable `PIIDetector` (built-in: `RegexPIIDetector`)
- `RateLimiter` with pluggable `RateLimitPolicy` (built-in: `InMemoryRateLimit`)
- `BudgetGatekeeper` with pluggable `CostProvider` (built-in: `ManualCostTracker`)
- `AuditLogger` with pluggable `AuditBackend` (built-in: `LogAuditBackend`)
- `ComplianceChecker` for payload size and VT consistency
- `UXHandler` for HITL message formatting

**Decision Lifecycle**
- `AOWWindow` and `AOWHandler` for temporal governance
- `DecisionDebt` and `DecisionDebtLedger` for deferred decision tracking
- Terminal state latching (expired/completed windows cannot revert)

**Domain Governance (BYOPA)**
- `GovernanceProfile` with per-domain VT floors
- `DomainBarrierHandler` for cross-domain information barriers
- Metadata-only cross-domain exchange

**Developer Experience**
- `@governed(vt=2)` decorator with `GovernanceError`
- TOML governance profiles via `load_pipeline_config()`
- 8 runnable examples (Pydantic AI, LangGraph, Anthropic SDK, and more)

**Interfaces**
- `PIIDetector`, `RateLimitPolicy`, `CostProvider`, `AuditBackend` ABCs
- `ApprovalBackend` ABC for HITL approval routing
- `DebtStore`, `AOWStore` ABCs for persistence

**Optional**
- `[amo]` extra: `DynamicVTHandler` with minimal-oversight integration
- `[presidio]` extra: Presidio PII detection backend

**Documentation**
- 9 governance principles with academic grounding (25 citations)
- Competitive landscape analysis
- Theory guide connecting paper equations to library code
- mkdocs site with Material theme
