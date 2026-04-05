"""Tests for GovernancePipeline -- the core middleware chain."""

from __future__ import annotations

import pytest

from governed_agents import (
    ActionContext,
    ExecutionMode,
    GovernanceHandler,
    GovernancePipeline,
    GovernanceResult,
    Verdict,
)


# ── Helper handlers ──────────────────────────────


class PassHandler(GovernanceHandler):
    """Always allows."""

    def __init__(self, handler_name: str = "pass") -> None:
        self._name = handler_name
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        self.call_count += 1
        return GovernanceResult.continue_(handler_name=self.name, reason="OK")


class BlockHandler(GovernanceHandler):
    """Always blocks."""

    def __init__(self, handler_name: str = "block") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        return GovernanceResult.abort(handler_name=self.name, reason="Blocked")


class ModifyHandler(GovernanceHandler):
    """Modifies the context by adding a key to metadata."""

    def __init__(self, handler_name: str = "modify", key: str = "modified") -> None:
        self._name = handler_name
        self._key = key

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        from dataclasses import replace

        new_metadata = dict(context.metadata)
        new_metadata[self._key] = True
        modified = replace(context, metadata=new_metadata)
        return GovernanceResult.modify(
            modified_context=modified,
            handler_name=self.name,
            reason="Modified",
        )


class FailHandler(GovernanceHandler):
    """Raises an exception."""

    def __init__(self, handler_name: str = "fail") -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        raise RuntimeError("Handler exploded")


class OrderTracker(GovernanceHandler):
    """Tracks execution order."""

    execution_order: list[str] = []

    def __init__(self, handler_name: str) -> None:
        self._name = handler_name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        OrderTracker.execution_order.append(self._name)
        return GovernanceResult.continue_(handler_name=self.name)


# ── Tests ────────────────────────────────────────


@pytest.fixture
def pipeline() -> GovernancePipeline:
    return GovernancePipeline()


@pytest.fixture
def ctx() -> ActionContext:
    return ActionContext(action="test_action", agent_id="test_agent")


class TestEmptyPipeline:
    async def test_empty_pipeline_continues(self, pipeline, ctx):
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW

    async def test_empty_pipeline_reason(self, pipeline, ctx):
        result = await pipeline.execute(ctx)
        assert "All handlers passed" in result.reason


class TestRegistration:
    def test_register_handler(self, pipeline):
        h = PassHandler()
        pipeline.register(h, priority=10)
        assert len(pipeline.handlers) == 1
        assert pipeline.handlers[0].handler is h

    def test_handlers_sorted_by_priority(self, pipeline):
        pipeline.register(PassHandler("c"), priority=30)
        pipeline.register(PassHandler("a"), priority=10)
        pipeline.register(PassHandler("b"), priority=20)
        names = [r.handler.name for r in pipeline.handlers]
        assert names == ["a", "b", "c"]

    def test_multiple_same_priority(self, pipeline):
        pipeline.register(PassHandler("x"), priority=10)
        pipeline.register(PassHandler("y"), priority=10)
        assert len(pipeline.handlers) == 2


class TestAddMethod:
    def test_add_auto_assigns_priority(self, pipeline):
        pipeline.add(PassHandler("a"))
        pipeline.add(PassHandler("b"))
        pipeline.add(PassHandler("c"))
        priorities = [r.priority for r in pipeline.handlers]
        assert priorities == [10, 20, 30]

    def test_add_starts_at_10(self, pipeline):
        pipeline.add(PassHandler("first"))
        assert pipeline.handlers[0].priority == 10

    def test_add_increments_from_last(self, pipeline):
        pipeline.register(PassHandler("explicit"), priority=50)
        pipeline.add(PassHandler("auto"))
        assert pipeline.handlers[-1].priority == 60

    def test_add_optional_kwarg(self, pipeline):
        pipeline.add(PassHandler("opt"), optional=True)
        assert pipeline.handlers[0].optional is True

    async def test_add_handlers_execute(self, pipeline, ctx):
        pipeline.add(PassHandler("a"))
        pipeline.add(PassHandler("b"))
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW


class TestSequentialExecution:
    async def test_all_pass(self, pipeline, ctx):
        pipeline.register(PassHandler("a"), priority=10)
        pipeline.register(PassHandler("b"), priority=20)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW

    async def test_block_short_circuits(self, pipeline, ctx):
        h1 = PassHandler("before")
        h2 = BlockHandler("blocker")
        h3 = PassHandler("after")
        pipeline.register(h1, priority=10)
        pipeline.register(h2, priority=20)
        pipeline.register(h3, priority=30)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.BLOCK
        assert result.handler_name == "blocker"
        assert h1.call_count == 1
        assert h3.call_count == 0

    async def test_modify_chains_context(self, pipeline, ctx):
        pipeline.register(ModifyHandler("m1", key="first"), priority=10)
        pipeline.register(ModifyHandler("m2", key="second"), priority=20)
        pipeline.register(PassHandler("end"), priority=30)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW


class TestParallelExecution:
    async def test_parallel_handlers_in_same_group(self, pipeline, ctx):
        h1 = PassHandler("p1")
        h2 = PassHandler("p2")
        pipeline.register(h1, priority=10, mode=ExecutionMode.PARALLEL)
        pipeline.register(h2, priority=10, mode=ExecutionMode.PARALLEL)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW
        assert h1.call_count == 1
        assert h2.call_count == 1

    async def test_parallel_block_stops_pipeline(self, pipeline, ctx):
        pipeline.register(PassHandler("p1"), priority=10, mode=ExecutionMode.PARALLEL)
        pipeline.register(BlockHandler("blocker"), priority=10, mode=ExecutionMode.PARALLEL)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.BLOCK


class TestPriorityGroups:
    async def test_groups_execute_in_order(self, pipeline, ctx):
        OrderTracker.execution_order = []
        pipeline.register(OrderTracker("group1"), priority=10)
        pipeline.register(OrderTracker("group2"), priority=20)
        pipeline.register(OrderTracker("group3"), priority=30)
        await pipeline.execute(ctx)
        assert OrderTracker.execution_order == ["group1", "group2", "group3"]


class TestGracefulDegradation:
    async def test_optional_handler_failure_skipped(self, pipeline, ctx):
        pipeline.register(PassHandler("before"), priority=10)
        pipeline.register(FailHandler("optional_fail"), priority=20, optional=True)
        pipeline.register(PassHandler("after"), priority=30)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW

    async def test_non_optional_handler_failure_blocks(self, pipeline, ctx):
        pipeline.register(FailHandler("required_fail"), priority=10, optional=False)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.BLOCK
        assert "required_fail" in result.handler_name


class TestDependencies:
    async def test_handler_with_unmet_deps_deferred(self, pipeline, ctx):
        OrderTracker.execution_order = []
        pipeline.register(
            OrderTracker("depends_on_a"),
            priority=10,
            depends_on=frozenset({"a"}),
        )
        pipeline.register(OrderTracker("a"), priority=20)
        await pipeline.execute(ctx)
        # "depends_on_a" should run after "a" (deferred from group 10 to group 20+)
        assert "a" in OrderTracker.execution_order
        a_idx = OrderTracker.execution_order.index("a")
        dep_idx = OrderTracker.execution_order.index("depends_on_a")
        assert dep_idx > a_idx
