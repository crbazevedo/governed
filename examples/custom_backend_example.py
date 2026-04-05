"""Custom backends -- implementing the pluggable interfaces.

Demonstrates PIIDetector, CostProvider, and AuditBackend with custom
logic plugged into the standard governance pipeline.

Run: python examples/custom_backend_example.py
"""

import asyncio
import os
from typing import Any

from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler
from governed_agents.handlers import AuditLogger, PIIFilter
from governed_agents.handlers.budget import BudgetGatekeeper
from governed_agents.interfaces import (
    AuditBackend, AuditEntry, CostProvider, PIIDetector, PIIMatch,
)


class BlocklistPIIDetector(PIIDetector):
    """Custom PII detector: word blocklist instead of regex."""

    def __init__(self, blocked_words: list[str]):
        self._blocked = {w.lower() for w in blocked_words}

    def scan(self, payload: dict[str, Any]) -> list[PIIMatch]:
        matches = []
        for key, val in payload.items():
            if isinstance(val, str):
                for word in val.lower().split():
                    if word in self._blocked:
                        matches.append(PIIMatch(field_path=key, pattern_name="blocklist"))
        return matches

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for key, val in payload.items():
            if isinstance(val, str):
                out[key] = " ".join(
                    "[BLOCKED]" if w.lower() in self._blocked else w
                    for w in val.split()
                )
            else:
                out[key] = val
        return out


class EnvVarCostProvider(CostProvider):
    """Custom cost provider: reads cumulative cost from an env var."""

    def __init__(self, env_var: str = "AGENT_COST_USD"):
        self._env_var = env_var

    def current_cost(self, agent_id: str | None = None) -> float:
        return float(os.environ.get(self._env_var, "0.0"))


class ListAuditBackend(AuditBackend):
    """Custom audit backend: stores entries in a plain Python list."""

    def __init__(self):
        self.entries: list[dict] = []

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append({"action": entry.action, "agent": entry.agent_id, "vt": entry.vt_tier})


async def main():
    print("=== Custom Backend Integration ===\n")
    os.environ["AGENT_COST_USD"] = "1.25"

    audit_be = ListAuditBackend()
    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter(detector=BlocklistPIIDetector(["confidential", "secret"])))
    pipeline.add(BudgetGatekeeper(budget_limit_usd=5.0, cost_provider=EnvVarCostProvider()))
    pipeline.add(VTGovernanceHandler())
    pipeline.add(AuditLogger(backend=audit_be), optional=True)

    ctx = ActionContext(
        action="summarize_doc", agent_id="analyst", vt_tier=1,
        payload={"text": "This document is confidential and contains secret data"},
    )
    result = await pipeline.execute(ctx)
    print(f"Verdict: {result.action.value}")
    if result.modified_context:
        print(f"Redacted: {result.modified_context.payload}")
    print(f"Audit entries: {audit_be.entries}")

    print("\n--- Budget exceeded scenario ---")
    os.environ["AGENT_COST_USD"] = "10.00"
    r2 = await pipeline.execute(ctx)
    print(f"Verdict: {r2.action.value} | {r2.reason}")


if __name__ == "__main__":
    asyncio.run(main())
