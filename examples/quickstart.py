"""Governed Agents -- Quick Start

Demonstrates the core governance pipeline with PII filtering,
rate limiting, VT tier enforcement, and audit logging.
Also demonstrates the @governed decorator and execution tracing.

Run: python examples/quickstart.py
"""

import asyncio

from governed_agents import (
    ActionContext,
    GovernancePipeline,
    VTGovernanceHandler,
)
from governed_agents.decorator import GovernanceError, configure, governed
from governed_agents.handlers import AuditLogger, PIIFilter, RateLimiter


async def main():
    # ── Pipeline API (explicit) ─────────────────────────────────
    print("=== Pipeline API ===\n")

    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())  # Redacts PII in payloads
    pipeline.add(RateLimiter(max_per_window=3))  # Frequency limit
    pipeline.add(VTGovernanceHandler())  # VT tier enforcement
    pipeline.add(AuditLogger(), optional=True)  # Audit log (optional)

    # --- VT1: agent acts, action is logged for review ---
    ctx1 = ActionContext(
        action="send_notification",
        agent_id="assistant",
        vt_tier=1,
        payload={"to": "user@example.com", "body": "Meeting reminder"},
    )
    r1 = await pipeline.execute(ctx1)
    print(
        f"VT1 action: {r1.action.value}"
    )  # -> allow (PII redacted + review flag applied internally)

    # --- VT2: requires human approval (blocked without it) ---
    ctx2 = ActionContext(
        action="send_email_to_client",
        agent_id="assistant",
        vt_tier=2,
        payload={"to": "client@corp.com", "body": "Proposal attached"},
    )
    r2 = await pipeline.execute(ctx2)
    print(f"VT2 action: {r2.action.value}")  # -> block
    print(f"  Reason: {r2.reason}")
    print(f"  Suggestion: {r2.suggestion}")  # Structured recovery guidance
    print(f"  Alternatives: {r2.alternatives}")

    # --- VT0: fully autonomous, no restrictions ---
    ctx3 = ActionContext(
        action="log_metric",
        agent_id="monitor",
        vt_tier=0,
        payload={"metric": "cpu_usage", "value": 42},
    )
    r3 = await pipeline.execute(ctx3)
    print(f"VT0 action: {r3.action.value}")  # -> allow

    # ── Execution Trace ─────────────────────────────────────────
    print("\n=== Execution Trace ===\n")

    trace = await pipeline.execute_traced(ctx3)
    print(f"Trace summary: {trace.summary}")
    for ht in trace.handler_traces:
        print(f"  {ht.handler_name}: {ht.verdict.value} ({ht.duration_ms:.2f}ms)")

    # ── Decorator API (minimal) ─────────────────────────────────
    print("\n=== @governed Decorator ===\n")

    configure(handlers=[PIIFilter(), VTGovernanceHandler()])

    @governed(vt=1)
    async def search_docs(query: str) -> str:
        return f"Results for: {query}"

    @governed(vt=2)
    async def send_email(to: str, body: str) -> None:
        print(f"Sending to {to}: {body}")

    # VT1 call succeeds
    result = await search_docs(query="quarterly revenue")
    print(f"search_docs: {result}")

    # VT2 call blocks with structured error
    try:
        await send_email(to="client@corp.com", body="See attached")
    except GovernanceError as e:
        print(f"send_email blocked: {e}")
        print(f"  Suggestion: {e.suggestion}")
        print(f"  Alternatives: {e.alternatives}")


if __name__ == "__main__":
    asyncio.run(main())
