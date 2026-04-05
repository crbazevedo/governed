"""LangGraph integration -- governance as a node in a workflow graph.

Adds a governance check node before a high-risk action in a
LangGraph-style workflow. VT2 triggers routing to human approval.

The LLM and LangGraph are mocked. The governance pattern is the focus.

Run: python examples/langgraph_example.py
"""

import asyncio

from governed_agents import (
    ActionContext, GovernancePipeline, Verdict, VTGovernanceHandler,
)
from governed_agents.handlers import PIIFilter


async def researcher(state: dict) -> dict:
    state["research"] = f"Key findings about '{state['topic']}'"
    print(f"  [researcher] {state['research']}")
    return state


async def writer(state: dict) -> dict:
    state["draft"] = f"Draft report on: {state['research']}"
    print(f"  [writer] {state['draft']}")
    return state


async def governance_gate(state: dict, pipeline: GovernancePipeline) -> dict:
    """Governance node: check before publishing (VT2)."""
    ctx = ActionContext(
        action="publish_report", agent_id="writer-agent", vt_tier=2,
        payload={"content": state["draft"]},
        metadata=state.get("gov_metadata", {}),
    )
    result = await pipeline.execute(ctx)
    state["gov_verdict"] = result.action.value
    state["gov_reason"] = result.reason
    print(f"  [governance] {result.action.value}")
    return state


async def publisher(state: dict) -> dict:
    state["published"] = True
    print(f"  [publisher] Published!")
    return state


async def human_review(state: dict) -> dict:
    state["awaiting_human"] = True
    print(f"  [human_review] Queued: {state['gov_reason']}")
    return state


async def run_graph(state: dict, pipeline: GovernancePipeline) -> dict:
    state = await researcher(state)
    state = await writer(state)
    state = await governance_gate(state, pipeline)
    if state["gov_verdict"] != Verdict.BLOCK.value:
        state = await publisher(state)
    else:
        state = await human_review(state)
    return state


async def main():
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(VTGovernanceHandler())

    print("=== LangGraph Governance Node ===\n")

    print("--- Run 1: No approval (VT2 blocks) ---")
    s1 = await run_graph({"topic": "Q4 results"}, pipeline)
    print(f"  published={s1.get('published', False)}, "
          f"awaiting_human={s1.get('awaiting_human', False)}\n")

    print("--- Run 2: Pre-approved (VT2 passes) ---")
    s2 = await run_graph(
        {"topic": "Q4 results", "gov_metadata": {"vt2_approved": True}},
        pipeline,
    )
    print(f"  published={s2.get('published', False)}")


if __name__ == "__main__":
    asyncio.run(main())
