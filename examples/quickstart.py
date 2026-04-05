"""Governed Agents -- Quick Start

Demonstrates the core governance pipeline with PII filtering,
rate limiting, VT tier enforcement, and audit logging.

Run: python examples/quickstart.py
"""

import asyncio

from governed_agents import (
    ActionContext,
    GovernancePipeline,
    Verdict,
    VTGovernanceHandler,
)
from governed_agents.handlers import AuditLogger, PIIFilter, RateLimiter


async def main():
    # Build a governance pipeline with four handlers
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())                          # Redacts PII in payloads
    pipeline.add(RateLimiter(max_per_window=3))        # Frequency limit
    pipeline.add(VTGovernanceHandler())                 # VT tier enforcement
    pipeline.add(AuditLogger(), optional=True)          # Audit log (optional)

    # --- VT1: agent acts, action is logged for review ---
    ctx1 = ActionContext(
        action="send_notification",
        agent_id="assistant",
        vt_tier=1,
        payload={"to": "user@example.com", "body": "Meeting reminder"},
    )
    r1 = await pipeline.execute(ctx1)
    print(f"VT1 action: {r1.action.value}")             # -> modify (PII redacted + review flag)

    # --- VT2: requires human approval (blocked without it) ---
    ctx2 = ActionContext(
        action="send_email_to_client",
        agent_id="assistant",
        vt_tier=2,
        payload={"to": "client@corp.com", "body": "Proposal attached"},
    )
    r2 = await pipeline.execute(ctx2)
    print(f"VT2 action: {r2.action.value}")             # -> block
    print(f"  Reason: {r2.reason}")

    # --- VT0: fully autonomous, no restrictions ---
    ctx3 = ActionContext(
        action="log_metric",
        agent_id="monitor",
        vt_tier=0,
        payload={"metric": "cpu_usage", "value": 42},
    )
    r3 = await pipeline.execute(ctx3)
    print(f"VT0 action: {r3.action.value}")             # -> allow


if __name__ == "__main__":
    asyncio.run(main())
