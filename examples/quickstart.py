"""Governed Agents -- Quick Start

Run: python examples/quickstart.py
"""

import asyncio

from governed_agents import (
    ActionContext,
    GovernancePipeline,
    VTGovernanceHandler,
)
from governed_agents.handlers import AuditLogger, PIIFilter, RateLimiter


async def main():
    # Create a governance pipeline
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(RateLimiter(max_per_window=3))
    pipeline.add(VTGovernanceHandler())
    pipeline.add(AuditLogger(backend="json", path="audit.jsonl"), optional=True)

    # Simulate a VT1 action (auto-approve with logging)
    ctx = ActionContext(
        action="send_notification",
        agent_id="assistant",
        vt_tier=1,
        payload={"to": "user@example.com", "body": "Meeting reminder"},
    )
    result = await pipeline.execute(ctx)
    print(f"VT1 action: {result.action.value}")  # -> allow

    # Simulate a VT2 action (requires approval)
    ctx2 = ActionContext(
        action="send_email_to_client",
        agent_id="assistant",
        vt_tier=2,
        payload={"to": "client@corp.com", "body": "Proposal attached"},
    )
    result2 = await pipeline.execute(ctx2)
    print(f"VT2 action: {result2.action.value}")  # -> block (needs human approval)
    print(f"  Reason: {result2.reason}")

    # Simulate a VT0 action (fully autonomous)
    ctx3 = ActionContext(
        action="log_metric",
        agent_id="monitor",
        vt_tier=0,
        payload={"metric": "cpu_usage", "value": 42},
    )
    result3 = await pipeline.execute(ctx3)
    print(f"VT0 action: {result3.action.value}")  # -> allow


if __name__ == "__main__":
    asyncio.run(main())
