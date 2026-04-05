"""UXHandler -- formats VT2+ actions as HITL messages for human review.

# Layer: Static (stateless governance handler)

Bridges the gap between the governance pipeline and human review UX.
For VT2+ actions, creates structured HITL messages that downstream
systems (Slack, CLI, web UI) can present to the human reviewer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace

from governed_agents.handler import (
    ActionContext,
    GovernanceHandler,
    GovernanceResult,
)
from governed_agents.hitl import HITLIntent, HITLMessage
from governed_agents.pii import redact_payload

logger = logging.getLogger(__name__)


class UXHandler(GovernanceHandler):
    """Formats VT2+ pipeline actions as HITL DECISION_REQUESTED messages.

    Runs before VT governance so it can format the request. The governance
    handler then gates the already-formatted request.

    For VT0-1 actions, passes through without intervention.
    For VT2+ actions, creates an HITLMessage and stores it in context
    metadata for the governance handler to find.
    """

    @property
    def name(self) -> str:
        return "ux_handler"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        vt = context.vt_tier

        # VT0-1: pass through without UX intervention
        if vt <= 1:
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"VT{vt}: no UX intervention needed",
            )

        # VT2+: format as DECISION_REQUESTED HITL message
        intent = HITLIntent.DECISION_REQUESTED
        if vt >= 4:
            intent = HITLIntent.ESCALATION

        trace_id = f"ux-{uuid.uuid4().hex[:8]}"

        summary = f"VT{vt} action requires approval: {context.action}"
        body = (
            f"**Action:** {context.action}\n"
            f"**Agent:** {context.agent_id}\n"
            f"**VT Tier:** {vt}\n"
            f"**Payload keys:** "
            f"{list(context.payload.keys()) if context.payload else 'none'}"
        )

        # Scrub PII from composed message text using the centralized pii module
        scrubbed = redact_payload({"summary": summary, "body": body})
        summary = scrubbed["summary"]
        body = scrubbed["body"]

        hitl_msg = HITLMessage(
            trace_id=trace_id,
            intent=intent,
            agent_id=context.agent_id or "unknown",
            vt_tier=vt,
            summary=summary,
            body=body,
            options=["Approve", "Deny"] if vt == 2 else [],
            timeout_seconds=1800 if vt == 2 else None,
        )

        # Store formatted message in metadata for downstream handlers
        new_metadata = dict(context.metadata)
        new_metadata["hitl_message"] = hitl_msg
        new_metadata["ux_trace_id"] = trace_id

        modified = replace(context, metadata=new_metadata)

        return GovernanceResult.modify(
            modified_context=modified,
            handler_name=self.name,
            reason=f"VT{vt} action formatted as {intent.value} HITL message",
        )
