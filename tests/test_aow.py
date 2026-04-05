"""Tests for Action Opportunity Windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from governed_agents.aow import AOWHandler, AOWState, AOWWindow
from governed_agents.handler import ActionContext, Verdict


# ── AOWWindow.evaluate() ──────────────────────────────────────────────


class TestAOWWindowEvaluate:
    def _now(self) -> datetime:
        return datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_pending_before_earliest(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now + timedelta(hours=1),
        )
        assert window.evaluate(now) == AOWState.PENDING

    def test_open_after_earliest_no_latest(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
        )
        assert window.evaluate(now) == AOWState.OPEN

    def test_expired_after_latest(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=2),
            latest=now - timedelta(hours=1),
        )
        assert window.evaluate(now) == AOWState.EXPIRED

    def test_optimal_near_optimal_time(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            optimal=now,
            latest=now + timedelta(hours=2),
        )
        assert window.evaluate(now) == AOWState.OPTIMAL

    def test_optimal_within_30_min(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            optimal=now - timedelta(minutes=20),
            latest=now + timedelta(hours=2),
        )
        assert window.evaluate(now) == AOWState.OPTIMAL

    def test_open_outside_optimal_window(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=2),
            optimal=now - timedelta(hours=1),
            latest=now + timedelta(hours=2),
        )
        assert window.evaluate(now) == AOWState.OPEN

    def test_expiring_within_threshold(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=2),
            latest=now + timedelta(minutes=15),
            expiry_warning_minutes=30,
        )
        assert window.evaluate(now) == AOWState.EXPIRING

    def test_blocked_by_dependency(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            blocked_by=["tests_pass"],
        )
        assert window.evaluate(now) == AOWState.BLOCKED

    def test_completed_stays_completed(self):
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
        )
        window.mark_completed()
        assert window.evaluate(now) == AOWState.COMPLETED

    def test_blocked_takes_priority_over_time(self):
        """Blocked should be returned even if time is within window."""
        now = self._now()
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            latest=now + timedelta(hours=1),
            blocked_by=["approval"],
        )
        assert window.evaluate(now) == AOWState.BLOCKED


# ── AOWWindow mutation methods ────────────────────────────────────────


class TestAOWWindowMutations:
    def test_mark_completed(self):
        window = AOWWindow(
            action_id="deploy",
            earliest=datetime.now(timezone.utc),
        )
        window.mark_completed()
        assert window.state == AOWState.COMPLETED

    def test_add_blocker(self):
        window = AOWWindow(
            action_id="deploy",
            earliest=datetime.now(timezone.utc),
        )
        window.add_blocker("tests_pass")
        assert "tests_pass" in window.blocked_by

    def test_add_blocker_idempotent(self):
        window = AOWWindow(
            action_id="deploy",
            earliest=datetime.now(timezone.utc),
        )
        window.add_blocker("tests_pass")
        window.add_blocker("tests_pass")
        assert window.blocked_by.count("tests_pass") == 1

    def test_remove_blocker(self):
        window = AOWWindow(
            action_id="deploy",
            earliest=datetime.now(timezone.utc),
            blocked_by=["tests_pass", "approval"],
        )
        window.remove_blocker("tests_pass")
        assert "tests_pass" not in window.blocked_by
        assert "approval" in window.blocked_by

    def test_remove_nonexistent_blocker_is_noop(self):
        window = AOWWindow(
            action_id="deploy",
            earliest=datetime.now(timezone.utc),
        )
        window.remove_blocker("nonexistent")  # Should not raise


# ── AOWHandler ────────────────────────────────────────────────────────


class TestAOWHandler:
    async def test_no_window_allows(self):
        handler = AOWHandler()
        ctx = ActionContext(action="deploy", agent_id="eng")
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_open_window_allows(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            latest=now + timedelta(hours=1),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_optimal_window_allows(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            optimal=now,
            latest=now + timedelta(hours=2),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.ALLOW

    async def test_expired_window_blocks(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=2),
            latest=now - timedelta(hours=1),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "expired" in result.reason

    async def test_pending_window_blocks(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now + timedelta(hours=1),
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "pending" in result.reason

    async def test_blocked_window_blocks(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            blocked_by=["tests"],
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.BLOCK
        assert "blocked" in result.reason

    async def test_expiring_window_modifies(self):
        handler = AOWHandler()
        now = datetime.now(timezone.utc)
        window = AOWWindow(
            action_id="deploy",
            earliest=now - timedelta(hours=1),
            latest=now + timedelta(minutes=10),
            expiry_warning_minutes=30,
        )
        ctx = ActionContext(
            action="deploy",
            agent_id="eng",
            metadata={"aow_windows": {"deploy": window}},
        )
        result = await handler.evaluate(ctx)
        assert result.action == Verdict.MODIFY
        assert result.modified_context is not None
        assert result.modified_context.metadata["aow_expiring"] is True
