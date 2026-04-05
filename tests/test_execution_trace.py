"""Tests for GAP 4: Pipeline Execution Trace.

Verifies that execute_traced() returns complete, accurate traces
with per-handler timing, verdicts, and recovery guidance.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from governed_agents import (
    ActionContext,
    ExecutionMode,
    ExecutionTrace,
    GovernanceHandler,
    GovernancePipeline,
    GovernanceResult,
    HandlerTrace,
    Verdict,
)


# ── Helper handlers ──────────────────────────────


class PassHandler(GovernanceHandler):
    def __init__(self, handler_name: str = "pass") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        return GovernanceResult.continue_(handler_name=self.name, reason="OK")


class BlockHandler(GovernanceHandler):
    def __init__(self, handler_name: str = "block") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        return GovernanceResult.abort(
            handler_name=self.name,
            reason="Blocked",
            suggestion="Fix the thing",
            alternatives=["Try A", "Try B"],
        )


class ModifyHandler(GovernanceHandler):
    def __init__(self, handler_name: str = "modify") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        new_meta = dict(context.metadata)
        new_meta["modified_by"] = self._name
        return GovernanceResult.modify(
            modified_context=replace(context, metadata=new_meta),
            handler_name=self.name,
            reason="Modified",
        )


class FailHandler(GovernanceHandler):
    def __init__(self, handler_name: str = "fail") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        raise RuntimeError("Handler exploded")


# ── Tests ────────────────────────────────────────


@pytest.fixture
def ctx() -> ActionContext:
    return ActionContext(action="test_action", agent_id="test_agent")


class TestExecuteTraced:
    async def test_empty_pipeline_trace(self, ctx):
        pipeline = GovernancePipeline()
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.ALLOW
        assert trace.handler_traces == []
        assert trace.total_duration_ms >= 0
        assert trace.context_modifications == 0

    async def test_single_pass_handler_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler("checker"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.ALLOW
        assert len(trace.handler_traces) == 1
        ht = trace.handler_traces[0]
        assert ht.handler_name == "checker"
        assert ht.verdict == Verdict.ALLOW
        assert ht.duration_ms >= 0

    async def test_block_handler_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler("pre"))
        pipeline.add(BlockHandler("blocker"))
        pipeline.add(PassHandler("post"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.BLOCK
        assert trace.final_reason == "Blocked"
        assert trace.suggestion == "Fix the thing"
        assert trace.alternatives == ["Try A", "Try B"]
        # "post" should not appear in traces (short-circuited)
        handler_names = [ht.handler_name for ht in trace.handler_traces]
        assert "pre" in handler_names
        assert "blocker" in handler_names
        assert "post" not in handler_names

    async def test_modify_handler_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(ModifyHandler("m1"))
        pipeline.add(ModifyHandler("m2"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.ALLOW
        assert trace.context_modifications == 2
        assert len(trace.handler_traces) == 2
        for ht in trace.handler_traces:
            assert ht.verdict == Verdict.MODIFY

    async def test_trace_timing(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler("a"))
        pipeline.add(PassHandler("b"))
        pipeline.add(PassHandler("c"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.total_duration_ms >= 0
        for ht in trace.handler_traces:
            assert ht.duration_ms >= 0

    async def test_trace_summary_format(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler("a"))
        pipeline.add(PassHandler("b"))
        trace = await pipeline.execute_traced(ctx)
        summary = trace.summary
        assert "allow" in summary
        assert "2 handlers" in summary
        assert "a" in summary
        assert "b" in summary
        assert "ms" in summary

    async def test_optional_handler_failure_in_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler("before"))
        pipeline.add(FailHandler("optional_fail"), optional=True)
        pipeline.add(PassHandler("after"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.ALLOW
        handler_names = [ht.handler_name for ht in trace.handler_traces]
        assert "optional_fail" in handler_names
        assert "after" in handler_names

    async def test_non_optional_failure_in_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(FailHandler("required_fail"))
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.BLOCK
        assert len(trace.handler_traces) == 1
        assert trace.handler_traces[0].handler_name == "required_fail"

    async def test_parallel_handlers_in_trace(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.register(PassHandler("p1"), priority=10, mode=ExecutionMode.PARALLEL)
        pipeline.register(PassHandler("p2"), priority=10, mode=ExecutionMode.PARALLEL)
        trace = await pipeline.execute_traced(ctx)
        assert trace.final_verdict == Verdict.ALLOW
        handler_names = {ht.handler_name for ht in trace.handler_traces}
        assert handler_names == {"p1", "p2"}


class TestExecuteConsistency:
    """Verify that execute() and execute_traced() produce the same verdict."""

    async def test_allow_consistency(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(PassHandler())
        result = await pipeline.execute(ctx)
        trace = await pipeline.execute_traced(ctx)
        assert result.action == trace.final_verdict
        assert result.reason == trace.final_reason

    async def test_block_consistency(self, ctx):
        pipeline = GovernancePipeline()
        pipeline.add(BlockHandler())
        result = await pipeline.execute(ctx)
        trace = await pipeline.execute_traced(ctx)
        assert result.action == trace.final_verdict
        assert result.reason == trace.final_reason


class TestHandlerTraceDataclass:
    def test_handler_trace_fields(self):
        ht = HandlerTrace(
            handler_name="test",
            verdict=Verdict.ALLOW,
            reason="ok",
            duration_ms=1.5,
        )
        assert ht.handler_name == "test"
        assert ht.suggestion == ""
        assert ht.alternatives == []

    def test_handler_trace_with_feedback(self):
        ht = HandlerTrace(
            handler_name="test",
            verdict=Verdict.BLOCK,
            reason="blocked",
            duration_ms=2.0,
            suggestion="fix it",
            alternatives=["A", "B"],
        )
        assert ht.suggestion == "fix it"
        assert ht.alternatives == ["A", "B"]


class TestExecutionTraceDataclass:
    def test_summary_property(self):
        trace = ExecutionTrace(
            final_verdict=Verdict.ALLOW,
            final_reason="All passed",
            handler_traces=[
                HandlerTrace("a", Verdict.ALLOW, "ok", 1.0),
                HandlerTrace("b", Verdict.MODIFY, "modified", 2.0),
            ],
            total_duration_ms=3.0,
            context_modifications=1,
        )
        s = trace.summary
        assert "allow" in s
        assert "3.0ms" in s
        assert "2 handlers" in s
