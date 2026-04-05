"""Declarative governance via TOML configuration.

Demonstrates loading governance profiles and pipelines from a TOML file
(Python 3.11+) or from a plain dict (all Python versions).

Shows both single-domain and multi-domain configuration patterns.

Run: python examples/toml_config_example.py
"""

import asyncio
import sys

from governed_agents import ActionContext
from governed_agents.profile_loader import (
    load_domain_config,
    load_pipeline_config,
    load_profile,
)


async def main():
    # ── Option 1: Load a single profile from a dict ──

    profile = load_profile(
        {
            "domain": "corporate",
            "default_vt": 2,
            "vt_floor": {"send_email": 2, "deploy": 3, "read_data": 0},
            "blocked_tools": ["personal_calendar"],
        }
    )
    print(f"Profile domain: {profile.domain}")
    print(f"  VT floor for 'deploy': {profile.get_vt_floor('deploy')}")
    print(f"  Is 'personal_calendar' allowed? {profile.is_tool_allowed('personal_calendar')}")
    print()

    # ── Option 2: Build pipeline from dict config ──

    pipeline = load_pipeline_config(
        {
            "handlers": ["pii_filter", "rate_limiter", "vt_governance", "audit"],
            "rate_limiter": {"max_per_window": 10, "window_seconds": 60},
        }
    )

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

    # ── Option 3: Multi-domain config from dict ──

    print("=== Multi-Domain Configuration ===\n")

    domain_cfg = load_domain_config(
        {
            "domains": {
                "personal": {
                    "default_vt": 1,
                    "pii_sensitivity": 1,
                    "vt_floor": {"read_email": 0, "send_email": 1},
                },
                "corporate": {
                    "default_vt": 2,
                    "audit_required": True,
                    "pii_sensitivity": 2,
                    "vt_floor": {"send_email": 2, "deploy": 3},
                    "blocked_tools": ["personal_calendar"],
                },
            },
            "barrier": {
                "allowed_fields": ["timestamp", "duration_minutes", "urgency"],
            },
            "pipeline": {
                "handlers": ["pii_filter", "vt_governance", "audit"],
            },
        }
    )

    print(f"Domains loaded: {list(domain_cfg.profiles.keys())}")
    for name, profile in domain_cfg.profiles.items():
        print(f"  {name}: default_vt={profile.default_vt}, pii={profile.pii_sensitivity}")
    print()

    # Personal domain: send_email at VT1 — domain sets floor to VT1
    ctx_personal = ActionContext(
        action="send_email",
        agent_id="assistant",
        vt_tier=1,
        payload={"to": "friend@example.com", "body": "Hey!"},
        metadata={"domain_scope": "personal"},
    )
    result_p = await domain_cfg.pipeline.execute(ctx_personal)
    print(f"Personal send_email (VT1): {result_p.action.value}")
    print(f"  Reason: {result_p.reason}")
    print()

    # Corporate domain: send_email at VT1 — domain elevates to VT2, blocks
    ctx_corp = ActionContext(
        action="send_email",
        agent_id="assistant",
        vt_tier=1,
        payload={"to": "client@corp.com", "body": "Proposal"},
        metadata={"domain_scope": "corporate"},
    )
    result_c = await domain_cfg.pipeline.execute(ctx_corp)
    print(f"Corporate send_email (VT1 → elevated): {result_c.action.value}")
    print(f"  Reason: {result_c.reason}")
    print()

    # ── Option 4: Load from TOML file (Python 3.11+ only) ──

    if sys.version_info >= (3, 11):
        from pathlib import Path

        toml_path = Path(__file__).parent / "governance.toml"
        if toml_path.exists():
            # Multi-domain from TOML
            domain_from_toml = load_domain_config(toml_path)
            print(f"TOML domains: {list(domain_from_toml.profiles.keys())}")

            ctx3 = ActionContext(
                action="read_email",
                agent_id="monitor",
                vt_tier=0,
                payload={"folder": "inbox"},
                metadata={"domain_scope": "personal"},
            )
            result3 = await domain_from_toml.pipeline.execute(ctx3)
            print(f"TOML personal read_email (VT0): {result3.action.value}")
    else:
        print("Skipping TOML file loading (requires Python 3.11+)")


if __name__ == "__main__":
    asyncio.run(main())
