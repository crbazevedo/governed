"""Benchmark the governance pipeline.

Measures:
- Empty pipeline latency (baseline)
- Single handler (VTGovernanceHandler) latency
- Full pipeline (5 handlers) latency
- 1000 sequential executions throughput
- Parallel pipeline execution (10 concurrent)
- Execution trace overhead (execute_traced vs execute)

Run: python benchmarks/bench_pipeline.py
"""

from __future__ import annotations

import asyncio
import statistics
import time


def _ns_to_ms(ns: int) -> float:
    return ns / 1_000_000


def _format_stats(times_ns: list[int]) -> dict[str, float]:
    """Compute p50, p95, p99 from a list of nanosecond timings."""
    times_ms = [_ns_to_ms(t) for t in sorted(times_ns)]
    n = len(times_ms)
    return {
        "p50": times_ms[int(n * 0.50)],
        "p95": times_ms[int(n * 0.95)],
        "p99": times_ms[int(n * 0.99)],
        "mean": statistics.mean(times_ms),
        "min": times_ms[0],
        "max": times_ms[-1],
    }


async def bench_empty_pipeline(n: int = 1000) -> list[int]:
    """Benchmark: empty pipeline (baseline overhead)."""
    from governed_agents import ActionContext, GovernancePipeline

    pipeline = GovernancePipeline()
    ctx = ActionContext(action="test", agent_id="bench", vt_tier=0)

    times = []
    for _ in range(n):
        start = time.perf_counter_ns()
        await pipeline.execute(ctx)
        times.append(time.perf_counter_ns() - start)
    return times


async def bench_single_handler(n: int = 1000) -> list[int]:
    """Benchmark: single VTGovernanceHandler (VT0 = fast path)."""
    from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler

    pipeline = GovernancePipeline()
    pipeline.add(VTGovernanceHandler())
    ctx = ActionContext(action="test", agent_id="bench", vt_tier=0)

    times = []
    for _ in range(n):
        start = time.perf_counter_ns()
        await pipeline.execute(ctx)
        times.append(time.perf_counter_ns() - start)
    return times


async def bench_full_pipeline(n: int = 1000) -> list[int]:
    """Benchmark: full pipeline with 5 handlers."""
    from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler
    from governed_agents.handlers import (
        AuditLogger,
        BudgetGatekeeper,
        PIIFilter,
        RateLimiter,
    )

    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(RateLimiter(max_per_window=100_000, window_seconds=3600))
    pipeline.add(VTGovernanceHandler())
    pipeline.add(BudgetGatekeeper(budget_limit_usd=999_999.0))
    pipeline.add(AuditLogger(), optional=True)

    ctx = ActionContext(
        action="test",
        agent_id="bench",
        vt_tier=0,
        payload={"message": "Hello world, no PII here"},
    )

    times = []
    for _ in range(n):
        start = time.perf_counter_ns()
        await pipeline.execute(ctx)
        times.append(time.perf_counter_ns() - start)
    return times


async def bench_full_pipeline_traced(n: int = 1000) -> list[int]:
    """Benchmark: full pipeline with execute_traced() to measure trace overhead."""
    from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler
    from governed_agents.handlers import (
        AuditLogger,
        BudgetGatekeeper,
        PIIFilter,
        RateLimiter,
    )

    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(RateLimiter(max_per_window=100_000, window_seconds=3600))
    pipeline.add(VTGovernanceHandler())
    pipeline.add(BudgetGatekeeper(budget_limit_usd=999_999.0))
    pipeline.add(AuditLogger(), optional=True)

    ctx = ActionContext(
        action="test",
        agent_id="bench",
        vt_tier=0,
        payload={"message": "Hello world, no PII here"},
    )

    times = []
    for _ in range(n):
        start = time.perf_counter_ns()
        await pipeline.execute_traced(ctx)
        times.append(time.perf_counter_ns() - start)
    return times


async def bench_concurrent(concurrency: int = 10, per_task: int = 100) -> list[int]:
    """Benchmark: parallel pipeline execution (N concurrent tasks)."""
    from governed_agents import ActionContext, GovernancePipeline, VTGovernanceHandler
    from governed_agents.handlers import PIIFilter, RateLimiter

    pipeline = GovernancePipeline()
    pipeline.add(PIIFilter())
    pipeline.add(RateLimiter(max_per_window=100_000, window_seconds=3600))
    pipeline.add(VTGovernanceHandler())

    ctx = ActionContext(action="test", agent_id="bench", vt_tier=0)

    async def run_batch() -> list[int]:
        times = []
        for _ in range(per_task):
            start = time.perf_counter_ns()
            await pipeline.execute(ctx)
            times.append(time.perf_counter_ns() - start)
        return times

    # Run N batches concurrently
    all_results = await asyncio.gather(*[run_batch() for _ in range(concurrency)])
    # Flatten
    return [t for batch in all_results for t in batch]


def print_table(rows: list[tuple[str, dict[str, float]]]) -> None:
    """Print a formatted benchmark results table."""
    header = f"{'Benchmark':<40} {'p50':>8} {'p95':>8} {'p99':>8} {'mean':>8} {'min':>8} {'max':>8}"
    separator = "-" * len(header)
    print(separator)
    print(header)
    print(separator)
    for name, stats in rows:
        print(
            f"{name:<40} "
            f"{stats['p50']:>7.3f}ms "
            f"{stats['p95']:>7.3f}ms "
            f"{stats['p99']:>7.3f}ms "
            f"{stats['mean']:>7.3f}ms "
            f"{stats['min']:>7.3f}ms "
            f"{stats['max']:>7.3f}ms"
        )
    print(separator)


async def main() -> None:
    print("governed-agents pipeline benchmarks")
    print(f"Iterations: 1000 per benchmark\n")

    rows: list[tuple[str, dict[str, float]]] = []

    print("Running: empty pipeline...")
    rows.append(("Empty pipeline (baseline)", _format_stats(await bench_empty_pipeline())))

    print("Running: single handler (VT)...")
    rows.append(("Single handler (VTGovernance)", _format_stats(await bench_single_handler())))

    print("Running: full pipeline (5 handlers)...")
    rows.append(("Full pipeline (5 handlers)", _format_stats(await bench_full_pipeline())))

    print("Running: full pipeline traced...")
    rows.append(("Full pipeline + execute_traced()", _format_stats(await bench_full_pipeline_traced())))

    print("Running: 10 concurrent x 100 each...")
    rows.append(("10 concurrent x 100 (3 handlers)", _format_stats(await bench_concurrent())))

    print()
    print_table(rows)

    # Throughput calculation
    full_times = await bench_full_pipeline()
    total_ns = sum(full_times)
    total_s = total_ns / 1_000_000_000
    throughput = len(full_times) / total_s
    print(f"\nFull pipeline throughput: {throughput:,.0f} executions/sec")


if __name__ == "__main__":
    asyncio.run(main())
