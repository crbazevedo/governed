"""UXHandler -- formats VT2+ actions as HITL messages for human review."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace

from governed_agents.handler import (
    CallbackContext,
    CallbackHandler,
    CallbackResult,
)
from governed_agents.hitl import HITLIntent, HITLMessage

logger = logging.getLogger(__name__)


class UXHandler(CallbackHandler):
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

    async def check(self, context: CallbackContext) -> CallbackResult:
        vt = context.vt_tier

        # VT0-1: pass through without UX intervention
        if vt <= 1:
            return CallbackResult.continue_(
                handler_name=self.name,
                reason=f"VT{vt}: no UX intervention needed",
            )

        # VT2+: format as DECISION_REQUESTED HITL message
        intent = HITLIntent.DECISION_REQUESTED
        if vt >= 4:
            intent = HITLIntent.ESCALATION

        trace_id = f"ux-{uuid.uuid4().hex[:8]}"

        hitl_msg = HITLMessage(
            trace_id=trace_id,
            intent=intent,
            agent_id=context.agent_id or "unknown",
            vt_tier=vt,
            summary=f"VT{vt} action requires approval: {context.action}",
            body=(
                f"**Action:** {context.action}\n"
                f"**Agent:** {context.agent_id}\n"
                f"**VT Tier:** {vt}\n"
                f"**Payload keys:** "
                f"{list(context.payload.keys()) if context.payload else 'none'}"
            ),
            options=["Approve", "Deny"] if vt == 2 else [],
            timeout_seconds=1800 if vt == 2 else None,
        )

        # Store formatted message in metadata for downstream handlers
        new_metadata = dict(context.metadata)
        new_metadata["hitl_message"] = hitl_msg
        new_metadata["ux_trace_id"] = trace_id

        modified = replace(context, metadata=new_metadata)

        return CallbackResult.modify(
            modified_context=modified,
            handler_name=self.name,
            reason=f"VT{vt} action formatted as {intent.value} HITL message",
        )
