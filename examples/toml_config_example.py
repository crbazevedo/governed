"""Declarative governance via TOML configuration.

Demonstrates loading governance profiles and pipelines from a TOML file
(Python 3.11+) or from a plain dict (all Python versions).

Run: python examples/toml_config_example.py
"""

import asyncio
import sys

from governed_agents import ActionContext, Verdict
from governed_agents.profile_loader import load_pipeline_config, load_profile


async def main():
    # ── Option 1: Load from a dict (works on all Python versions) ──

    profile = load_profile({
        "domain": "corporate",
        "default_vt": 2,
        "vt_floor": {"send_email": 2, "deploy": 3, "read_data": 0},
        "blocked_tools": ["personal_calendar"],
    })
    print(f"Profile domain: {profile.domain}")
    print(f"  VT floor for 'deploy': {profile.get_vt_floor('deploy')}")
    print(f"  Is 'personal_calendar' allowed? {profile.is_tool_allowed('personal_calendar')}")
    print()

    # ── Option 2: Build pipeline from dict config ──

    pipeline = load_pipeline_config({
        "handlers": ["pii_filter", "rate_limiter", "vt_governance", "audit"],
        "rate_limiter": {"max_per_window": 10, "window_seconds": 60},
    })

    # Test with a VT1 action (should pass)
    ctx = ActionContext(
        action="search_docs",
        agent_id="assistant",
        vt_tier=1,
        payload={"query": "quarterly revenue"},
    )
    result = await pipeline.execute(ctx)
    print(f"VT1 search_docs: {result.action.value}")
    print(f"  Reason: {result.reason}")
    print()

    # Test with a VT2 action without approval (should block)
    ctx2 = ActionContext(
        action="send_email",
        agent_id="assistant",
        vt_tier=2,
        payload={"to": "client@corp.com", "body": "Proposal attached"},
    )
    result2 = await pipeline.execute(ctx2)
    print(f"VT2 send_email (no approval): {result2.action.value}")
    print(f"  Reason: {result2.reason}")
    if result2.suggestion:
        print(f"  Suggestion: {result2.suggestion}")
    if result2.alternatives:
        print(f"  Alternatives: {result2.alternatives}")
    print()

    # ── Option 3: Load from TOML file (Python 3.11+ only) ──

    if sys.version_info >= (3, 11):
        from pathlib import Path

        toml_path = Path(__file__).parent / "governance.toml"
        if toml_path.exists():
            pipeline_from_toml = load_pipeline_config(toml_path)
            ctx3 = ActionContext(
                action="read_data",
                agent_id="monitor",
                vt_tier=0,
                payload={"metric": "cpu"},
            )
            result3 = await pipeline_from_toml.execute(ctx3)
            print(f"TOML pipeline - VT0 read_data: {result3.action.value}")
    else:
        print("Skipping TOML file loading (requires Python 3.11+)")


if __name__ == "__main__":
    asyncio.run(main())
