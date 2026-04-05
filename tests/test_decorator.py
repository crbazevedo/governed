"""Tests for GAP 3: @governed decorator and GovernanceError."""

from __future__ import annotations

import pytest

from governed_agents import ActionContext, GovernancePipeline, Verdict
from governed_agents.decorator import (
    GovernanceError,
    configure,
    get_pipeline,
    governed,
    reset_pipeline,
)
from governed_agents.handlers import PIIFilter
from governed_agents.vt import VTGovernanceHandler


@pytest.fixture(autouse=True)
def _reset():
    """Reset global pipeline state before and after each test."""
    reset_pipeline()
    yield
    reset_pipeline()


# ── GovernanceError ───────────────────────────────────────


class TestGovernanceError:
    def test_error_carries_result(self):
        from governed_agents import GovernanceResult

        result = GovernanceResult.abort(
            handler_name="test",
            reason="blocked",
            suggestion="try X",
            alternatives=["A", "B"],
        )
        err = GovernanceError(result)
        assert str(err) == "blocked"
        assert err.suggestion == "try X"
        assert err.alternatives == ["A", "B"]
        assert err.result is result


# ── configure() ───────────────────────────────────────────


class TestConfigure:
    def test_configure_with_handlers(self):
        pipeline = configure(handlers=[VTGovernanceHandler()])
        assert len(pipeline.handlers) == 1

    def test_configure_with_pipeline(self):
        p = GovernancePipeline()
        p.add(VTGovernanceHandler())
        configured = configure(pipeline=p)
        assert configured is p

    def test_configure_raises_without_args(self):
        with pytest.raises(ValueError, match="requires either"):
            configure()

    def test_get_pipeline_creates_empty_if_none(self):
        pipeline = get_pipeline()
        assert isinstance(pipeline, GovernancePipeline)
        assert len(pipeline.handlers) == 0


# ── @governed on async functions ──────────────────────────


class TestGovernedAsync:
    async def test_vt0_allows_execution(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0)
        async def read_data() -> str:
            return "data"

        result = await read_data()
        assert result == "data"

    async def test_vt1_allows_with_logging(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=1)
        async def search_docs(query: str) -> str:
            return f"results for {query}"

        result = await search_docs(query="test")
        assert result == "results for test"

    async def test_vt2_blocks_without_approval(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=2)
        async def send_email(to: str, body: str) -> None:
            pass  # Should not reach here

        with pytest.raises(GovernanceError) as exc_info:
            await send_email(to="test@example.com", body="hi")

        err = exc_info.value
        assert "requires owner approval" in str(err)
        assert err.suggestion != ""
        assert len(err.alternatives) > 0

    async def test_vt4_blocks(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=4)
        async def delete_all() -> None:
            pass

        with pytest.raises(GovernanceError) as exc_info:
            await delete_all()

        assert "owner-only" in str(exc_info.value).lower()

    async def test_pii_redaction_modifies_args(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0, pii=True)
        async def process(data: str) -> str:
            return data

        result = await process(data="Contact: user@example.com")
        assert "user@example.com" not in result

    async def test_custom_action_name(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0, action="custom_action_name")
        async def do_thing() -> str:
            return "done"

        result = await do_thing()
        assert result == "done"

    async def test_function_with_positional_args(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0)
        async def add(a: int, b: int) -> int:
            return a + b

        result = await add(3, 4)
        assert result == 7

    async def test_function_preserves_kwargs(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0)
        async def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        result = await greet(name="World")
        assert result == "Hello, World!"


# ── @governed on sync functions ───────────────────────────


class TestGovernedSync:
    def test_sync_vt0_allows(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=0)
        def sync_read() -> str:
            return "sync data"

        result = sync_read()
        assert result == "sync data"

    def test_sync_vt2_blocks(self):
        configure(handlers=[VTGovernanceHandler()])

        @governed(vt=2)
        def sync_send() -> None:
            pass

        with pytest.raises(GovernanceError):
            sync_send()


# ── Empty pipeline ────────────────────────────────────────


class TestGovernedEmptyPipeline:
    async def test_no_handlers_allows_everything(self):
        """With no handlers configured, all actions pass."""

        @governed(vt=4)
        async def anything() -> str:
            return "free"

        result = await anything()
        assert result == "free"
