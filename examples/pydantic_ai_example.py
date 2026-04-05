"""Pydantic AI integration -- wrapping agent tool calls with governance.

Demonstrates how to intercept tool calls from a Pydantic AI agent and
route them through the governed-agents pipeline before execution.

The LLM is mocked. The governance wrapping pattern is the focus.

Run: python examples/pydantic_ai_example.py
"""

import asyncio
from dataclasses import dataclass

from governed_agents import (
    ActionContext,
    GovernancePipeline,
    Verdict,
    VTGovernanceHandler,
)
from governed_agents.handlers import PIIFilter

# --- Tool registry with VT tiers ---

TOOLS = {
    "search_docs": {"vt_tier": 1, "description": "Search internal docs"},
    "send_email": {"vt_tier": 2, "description": "Send email to external recipient"},
}


@dataclass
class ToolCall:
    """Simulates a Pydantic AI tool call result."""

    name: str
    args: dict


async def govern_tool_call(pipeline: GovernancePipeline, call: ToolCall) -> str:
    """Wrap a tool call with governance -- the core integration pattern."""
    tool_cfg = TOOLS.get(call.name, {"vt_tier": 3})
    ctx = ActionContext(
        action=call.name,
        agent_id="pydantic-ai-agent",
        vt_tier=tool_cfg["vt_tier"],
        payload=call.args,
    )
    result = await pipeline.execute(ctx)

    if result.action == Verdict.BLOCK:
        return f"BLOCKED: {result.reason}"

    # In a real integration, execute the tool here
    return f"EXECUTED: {call.name}({call.args})"


async def main():
    # Build the governance pipeline
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(VTGovernanceHandler())

    # Simulate agent producing tool calls (mock -- no real LLM)
    tool_calls = [
        ToolCall("search_docs", {"query": "quarterly revenue"}),
        ToolCall("send_email", {"to": "client@example.com", "body": "See attached report"}),
    ]

    print("=== Pydantic AI Governance Wrapper ===\n")
    for call in tool_calls:
        tier = TOOLS.get(call.name, {}).get("vt_tier", "?")
        print(f"Tool: {call.name} (VT{tier})")
        outcome = await govern_tool_call(pipeline, call)
        print(f"  -> {outcome}\n")


if __name__ == "__main__":
    asyncio.run(main())
