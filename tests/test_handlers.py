"""Tests for built-in governance handlers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governed_agents import CallbackContext, ResultAction
from governed_agents.handlers import (
    AuditLogger,
    BudgetGatekeeper,
    ComplianceChecker,
    PIIFilter,
    RateLimiter,
    UXHandler,
)


# ── PIIFilter ────────────────────────────────────


class TestPIIFilter:
    async def test_no_pii_continues(self):
        f = PIIFilter()
        ctx = CallbackContext(
            action="test", payload={"message": "Hello world"}
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_email_detected_and_redacted(self):
        f = PIIFilter()
        ctx = CallbackContext(
            action="test", payload={"to": "user@example.com"}
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert "[REDACTED]" in result.modified_context.payload["to"]

    async def test_phone_detected_and_redacted(self):
        f = PIIFilter(patterns=[r"\b\d{3}-\d{3}-\d{4}\b"])
        ctx = CallbackContext(
            action="test", payload={"phone": "555-123-4567"}
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert "555-123-4567" not in result.modified_context.payload["phone"]

    async def test_redaction_disabled_aborts(self):
        f = PIIFilter(redact=False)
        ctx = CallbackContext(
            action="test", payload={"email": "user@example.com"}
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.ABORT

    async def test_nested_dict_redaction(self):
        f = PIIFilter()
        ctx = CallbackContext(
            action="test",
            payload={"nested": {"contact": "user@example.com"}},
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert "[REDACTED]" in result.modified_context.payload["nested"]["contact"]

    async def test_list_redaction(self):
        f = PIIFilter()
        ctx = CallbackContext(
            action="test",
            payload={"emails": ["a@b.com", "c@d.com"]},
        )
        result = await f.check(ctx)
        assert result.action == ResultAction.MODIFY
        for item in result.modified_context.payload["emails"]:
            assert "@" not in item

    async def test_original_payload_not_mutated(self):
        f = PIIFilter()
        original = {"to": "user@example.com"}
        ctx = CallbackContext(action="test", payload=original)
        await f.check(ctx)
        assert original["to"] == "user@example.com"


# ── RateLimiter ──────────────────────────────────


class TestRateLimiter:
    async def test_under_limit_continues(self):
        rl = RateLimiter(max_concurrent=3, window_seconds=60)
        ctx = CallbackContext(action="test", agent_id="bot")
        result = await rl.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_exceeds_limit_aborts(self):
        rl = RateLimiter(max_concurrent=2, window_seconds=60)
        ctx = CallbackContext(action="test", agent_id="bot")
        await rl.check(ctx)  # 1
        await rl.check(ctx)  # 2
        result = await rl.check(ctx)  # 3 -> over limit
        assert result.action == ResultAction.ABORT
        assert "Rate limit exceeded" in result.reason

    async def test_different_agents_independent(self):
        rl = RateLimiter(max_concurrent=1, window_seconds=60)
        ctx1 = CallbackContext(action="test", agent_id="bot1")
        ctx2 = CallbackContext(action="test", agent_id="bot2")
        r1 = await rl.check(ctx1)
        r2 = await rl.check(ctx2)
        assert r1.action == ResultAction.CONTINUE
        assert r2.action == ResultAction.CONTINUE


# ── BudgetGatekeeper ─────────────────────────────


class TestBudgetGatekeeper:
    async def test_under_budget_continues(self):
        bg = BudgetGatekeeper(budget_limit_usd=10.0, cost_callback=lambda: 5.0)
        ctx = CallbackContext(action="test")
        result = await bg.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_over_budget_aborts(self):
        bg = BudgetGatekeeper(budget_limit_usd=5.0, cost_callback=lambda: 6.0)
        ctx = CallbackContext(action="test")
        result = await bg.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "Budget exceeded" in result.reason

    async def test_exact_budget_aborts(self):
        bg = BudgetGatekeeper(budget_limit_usd=5.0, cost_callback=lambda: 5.0)
        ctx = CallbackContext(action="test")
        result = await bg.check(ctx)
        assert result.action == ResultAction.ABORT

    async def test_metadata_cost(self):
        bg = BudgetGatekeeper(budget_limit_usd=10.0)
        ctx = CallbackContext(
            action="test", metadata={"current_cost_usd": 3.0}
        )
        result = await bg.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_add_cost_manual(self):
        bg = BudgetGatekeeper(budget_limit_usd=5.0)
        bg.add_cost(4.0)
        ctx = CallbackContext(action="test")
        result = await bg.check(ctx)
        assert result.action == ResultAction.CONTINUE
        bg.add_cost(2.0)
        result = await bg.check(ctx)
        assert result.action == ResultAction.ABORT


# ── AuditLogger ──────────────────────────────────


class TestAuditLogger:
    async def test_logs_entry(self):
        al = AuditLogger(backend="json", path="/dev/null")
        ctx = CallbackContext(action="test", agent_id="bot", vt_tier=1)
        result = await al.check(ctx)
        assert result.action == ResultAction.CONTINUE
        assert len(al.entries) == 1
        assert al.entries[0].action == "test"

    async def test_json_file_written(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        al = AuditLogger(backend="json", path=path)
        ctx = CallbackContext(action="audit_test", agent_id="bot", vt_tier=0)
        await al.check(ctx)

        content = Path(path).read_text()
        record = json.loads(content.strip())
        assert record["action"] == "audit_test"
        assert record["agent_id"] == "bot"

    async def test_multiple_entries(self):
        al = AuditLogger(backend="json", path="/dev/null")
        for i in range(5):
            ctx = CallbackContext(action=f"action_{i}", agent_id="bot")
            await al.check(ctx)
        assert len(al.entries) == 5


# ── ComplianceChecker ────────────────────────────


class TestComplianceChecker:
    async def test_passes_valid_context(self):
        cc = ComplianceChecker()
        ctx = CallbackContext(action="test", agent_id="bot", vt_tier=0)
        result = await cc.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_rejects_oversized_payload(self):
        cc = ComplianceChecker(max_payload_kb=1)  # 1 KB limit
        big_payload = {"data": "x" * 2048}
        ctx = CallbackContext(action="test", agent_id="bot", payload=big_payload)
        result = await cc.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "Payload size" in result.reason

    async def test_vt1_requires_agent_id(self):
        cc = ComplianceChecker()
        ctx = CallbackContext(action="test", agent_id="", vt_tier=1)
        result = await cc.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "agent_id" in result.reason

    async def test_vt_consistency(self):
        cc = ComplianceChecker()
        ctx = CallbackContext(
            action="test", agent_id="bot", vt_tier=1,
            metadata={"governance_vt_tier": 2},
        )
        result = await cc.check(ctx)
        assert result.action == ResultAction.ABORT
        assert "mismatch" in result.reason

    async def test_non_strict_mode_continues(self):
        cc = ComplianceChecker(max_payload_kb=1, strict_mode=False)
        big_payload = {"data": "x" * 2048}
        ctx = CallbackContext(action="test", agent_id="bot", payload=big_payload)
        result = await cc.check(ctx)
        assert result.action == ResultAction.MODIFY
        assert "compliance_warnings" in result.modified_context.metadata


# ── UXHandler ────────────────────────────────────


class TestUXHandler:
    async def test_vt0_passes_through(self):
        ux = UXHandler()
        ctx = CallbackContext(action="test", vt_tier=0)
        result = await ux.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_vt1_passes_through(self):
        ux = UXHandler()
        ctx = CallbackContext(action="test", vt_tier=1)
        result = await ux.check(ctx)
        assert result.action == ResultAction.CONTINUE

    async def test_vt2_creates_hitl_message(self):
        ux = UXHandler()
        ctx = CallbackContext(action="send_email", agent_id="bot", vt_tier=2)
        result = await ux.check(ctx)
        assert result.action == ResultAction.MODIFY
        msg = result.modified_context.metadata.get("hitl_message")
        assert msg is not None
        assert msg.intent.value == "decision_requested"
        assert "send_email" in msg.summary

    async def test_vt4_escalation_intent(self):
        ux = UXHandler()
        ctx = CallbackContext(action="dangerous", agent_id="bot", vt_tier=4)
        result = await ux.check(ctx)
        assert result.action == ResultAction.MODIFY
        msg = result.modified_context.metadata.get("hitl_message")
        assert msg.intent.value == "escalation"
