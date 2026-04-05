"""Anthropic SDK integration -- governing Claude's tool_use calls.

Demonstrates wrapping raw Anthropic API tool_use results with the
governance pipeline. Each tool has a VT tier; the pipeline enforces
policy before execution.

The API call is mocked. The governance enforcement pattern is the focus.

Run: python examples/anthropic_sdk_example.py
"""

import asyncio

from governed_agents import (
    ActionContext,
    GovernancePipeline,
    Verdict,
    VTGovernanceHandler,
)
from governed_agents.handlers import PIIFilter

# --- Tool definitions with VT tiers ---

TOOL_REGISTRY = {
    "get_weather": {"vt_tier": 0, "desc": "Fetch weather data (autonomous)"},
    "search_calendar": {"vt_tier": 1, "desc": "Read calendar events (logged)"},
    "send_slack_msg": {"vt_tier": 2, "desc": "Post to Slack channel (needs approval)"},
}

# --- Mock API response containing tool_use blocks ---

MOCK_TOOL_CALLS = [
    {"type": "tool_use", "name": "get_weather", "input": {"city": "London"}},
    {"type": "tool_use", "name": "search_calendar", "input": {"date": "2025-01-15"}},
    {
        "type": "tool_use",
        "name": "send_slack_msg",
        "input": {
            "channel": "#clients",
            "text": "Meeting at 3pm with alice@corp.com",
        },
    },
]


async def execute_tool(name: str, args: dict) -> str:
    return f"[result for {name}]"


async def main():
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(VTGovernanceHandler())

    print("=== Anthropic SDK Governance Wrapper ===\n")

    for call in MOCK_TOOL_CALLS:
        name = call["name"]
        args = call["input"]
        tool_cfg = TOOL_REGISTRY[name]
        vt = tool_cfg["vt_tier"]

        ctx = ActionContext(
            action=name,
            agent_id="claude-assistant",
            vt_tier=vt,
            payload=args,
        )
        result = await pipeline.execute(ctx)

        print(f"Tool: {name} (VT{vt} - {tool_cfg['desc']})")

        if result.action == Verdict.BLOCK:
            print(f"  BLOCKED: {result.reason}\n")
        else:
            # Use the potentially modified context (PII-redacted payload)
            final_payload = result.modified_context.payload if result.modified_context else args
            output = await execute_tool(name, final_payload)
            label = "auto" if vt == 0 else "logged for review"
            print(f"  EXECUTED ({label}): {output}")
            if final_payload != args:
                print(f"  Payload was PII-redacted: {final_payload}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
