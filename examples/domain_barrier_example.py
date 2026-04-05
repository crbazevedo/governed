"""BYOPA domain barrier -- cross-domain governance with information barriers.

Demonstrates different VT floors per domain and cross-domain payload
filtering (content blocked, metadata passes).

Run: python examples/domain_barrier_example.py
"""

import asyncio

from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler
from governed_agents.handler import GovernanceHandler, GovernanceResult
from governed_agents.domain import (
    DomainBarrierHandler, DomainScope, GovernanceProfile,
)

PROFILES = {
    DomainScope.PERSONAL: GovernanceProfile(
        domain=DomainScope.PERSONAL,
        vt_floor={"send_message": 1, "transfer_funds": 3}, default_vt=1,
    ),
    DomainScope.CORPORATE: GovernanceProfile(
        domain=DomainScope.CORPORATE,
        vt_floor={"send_message": 2, "transfer_funds": 4}, default_vt=2,
    ),
}


class ContextCapture(GovernanceHandler):
    """Helper: captures the context after upstream modifications."""
    captured = None

    @property
    def name(self): return "capture"

    async def evaluate(self, context):
        ContextCapture.captured = context
        return GovernanceResult.continue_(handler_name=self.name)


async def main():
    print("=== BYOPA Domain Barrier ===\n")
    barrier = DomainBarrierHandler(profiles=PROFILES)

    # --- Same action, different domain = different VT floor ---
    print("--- VT Floor Elevation ---")
    print("  (send_message: VT1 in personal, VT2 in corporate)\n")
    for domain in [DomainScope.PERSONAL, DomainScope.CORPORATE]:
        pipeline = GovernancePipeline()
        pipeline.add(barrier)
        pipeline.add(VTGovernanceHandler())
        ctx = ActionContext(
            action="send_message", agent_id="assistant", vt_tier=1,
            payload={"text": "Hello"}, metadata={"domain_scope": domain},
        )
        result = await pipeline.execute(ctx)
        floor = PROFILES[domain].get_vt_floor("send_message")
        tag = "elevated to VT2" if floor > 1 else "stays VT1"
        print(f"  {domain.value:10s} | floor VT{floor} ({tag}) | final: {result.action.value}")

    # --- Cross-domain payload filtering ---
    print("\n--- Cross-Domain Information Barrier ---")
    print("  (corporate -> personal: only metadata fields pass)\n")
    pipe = GovernancePipeline()
    pipe.add(DomainBarrierHandler(profiles=PROFILES))
    pipe.add(ContextCapture())

    ctx = ActionContext(
        action="sync_calendar", agent_id="scheduler", vt_tier=1,
        payload={
            "meeting_title": "Strategy (CONFIDENTIAL)", "attendees": "alice@corp.com",
            "timestamp": "2025-03-15T10:00Z", "duration_minutes": 60, "urgency": "high",
        },
        metadata={"domain_scope": DomainScope.CORPORATE,
                   "target_domain": DomainScope.PERSONAL},
    )
    await pipe.execute(ctx)
    cap = ContextCapture.captured
    print(f"  Original: {list(ctx.payload.keys())}")
    print(f"  Passed:   {cap.payload}")
    print(f"  Blocked:  {cap.metadata.get('blocked_fields', [])}")


if __name__ == "__main__":
    asyncio.run(main())
