"""@governed decorator -- the simplest way to add governance to any function.

Wraps sync or async functions with governance pipeline enforcement.
The decorated function only executes if the pipeline allows it.
If blocked, raises ``GovernanceError`` with structured recovery guidance
(suggestion + alternatives).

Usage::

    from governed_agents import governed, configure
    from governed_agents.handlers import PIIFilter
    from governed_agents.vt import VTGovernanceHandler

    # Configure once at startup
    configure(handlers=[PIIFilter(), VTGovernanceHandler()])

    # Decorate functions
    @governed(vt=2)
    async def send_email(to: str, body: str):
        print(f"Sending to {to}: {body}")

    # If VT2 approval is missing, raises GovernanceError with
    # result.suggestion and result.alternatives for self-repair.

The decorator bridges the gap between "I have a governance pipeline" and
"all my agent tools are governed" -- two lines of code instead of ten.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable, TypeVar

from governed_agents.handler import ActionContext, GovernanceResult, Verdict
from governed_agents.pipeline import GovernancePipeline

F = TypeVar("F", bound=Callable[..., Any])


class GovernanceError(Exception):
    """Raised when a governed action is blocked by the pipeline.

    Carries the full ``GovernanceResult`` including ``suggestion`` and
    ``alternatives`` so that callers (or agents) can programmatically
    inspect what went wrong and how to recover.
    """

    def __init__(self, result: GovernanceResult) -> None:
        self.result = result
        self.suggestion = result.suggestion
        self.alternatives = list(result.alternatives)
        super().__init__(result.reason)


# ──────────────────────────────────────────────
# Module-level default pipeline
# ──────────────────────────────────────────────

_default_pipeline: GovernancePipeline | None = None


def configure(
    handlers: list[Any] | None = None,
    pipeline: GovernancePipeline | None = None,
) -> GovernancePipeline:
    """Configure the module-level default pipeline used by @governed.

    Call this once at startup. Either pass a pre-built pipeline or a list
    of handler instances (which will be added in order with auto-priority).

    Args:
        handlers: List of GovernanceHandler instances. Added with ``pipeline.add()``.
        pipeline: A pre-configured GovernancePipeline. Takes precedence over handlers.

    Returns:
        The configured pipeline (for chaining or inspection).

    Raises:
        ValueError: If neither handlers nor pipeline is provided.
    """
    global _default_pipeline

    if pipeline is not None:
        _default_pipeline = pipeline
        return _default_pipeline

    if handlers is not None:
        _default_pipeline = GovernancePipeline()
        for handler in handlers:
            _default_pipeline.add(handler)
        return _default_pipeline

    raise ValueError("configure() requires either handlers= or pipeline=")


def get_pipeline() -> GovernancePipeline:
    """Return the current default pipeline, creating an empty one if needed."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = GovernancePipeline()
    return _default_pipeline


def reset_pipeline() -> None:
    """Reset the default pipeline to None. Useful for testing."""
    global _default_pipeline
    _default_pipeline = None


# ──────────────────────────────────────────────
# @governed decorator
# ──────────────────────────────────────────────


def governed(
    vt: int = 1,
    pii: bool = False,
    domain: str = "",
    action: str = "",
    agent_id: str = "",
) -> Callable[[F], F]:
    """Decorator that wraps a function with governance pipeline enforcement.

    The decorated function is evaluated against the default pipeline before
    execution.  If the pipeline returns BLOCK, a ``GovernanceError`` is
    raised with the full result (including suggestion/alternatives).  If the
    pipeline returns MODIFY, the modified payload is unpacked back into the
    function's keyword arguments.

    Args:
        vt: VT risk tier for this function (0-4).
        pii: If True, a PIIFilter handler is prepended to the pipeline
             for this call (even if the default pipeline doesn't include one).
        domain: Domain scope tag (e.g. "corporate", "personal").
        action: Override the action name (defaults to function name).
        agent_id: Override the agent ID in the context.

    Returns:
        Decorated function that enforces governance before execution.
    """

    def decorator(fn: F) -> F:
        fn_action = action or fn.__name__
        is_async = inspect.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            pipeline = get_pipeline()

            # Build context from function signature
            sig = inspect.signature(fn)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            payload = dict(bound.arguments)

            ctx = ActionContext(
                action=fn_action,
                agent_id=agent_id,
                vt_tier=vt,
                payload=payload,
                metadata={"domain_scope": domain} if domain else {},
            )

            # Optionally prepend a PII filter for this call
            if pii:
                from governed_agents.handlers.pii_filter import PIIFilter

                effective_pipeline = GovernancePipeline()
                effective_pipeline.add(PIIFilter())
                for reg in pipeline.handlers:
                    effective_pipeline.register(
                        reg.handler,
                        priority=reg.priority + 10,
                        mode=reg.mode,
                        optional=reg.optional,
                        depends_on=reg.depends_on,
                    )
            else:
                effective_pipeline = pipeline

            # execute_with_context returns both the result AND the final
            # (possibly modified) context, so we can propagate PII redaction
            # and other transformations back to the function arguments.
            result, final_ctx = await effective_pipeline.execute_with_context(ctx)

            if result.action == Verdict.BLOCK:
                raise GovernanceError(result)

            # If the pipeline modified the context (e.g. PII redaction),
            # propagate changes back to the function call arguments.
            if final_ctx.payload != payload:
                modified_payload = final_ctx.payload
                # Re-bind: use modified values for kwargs
                for param_name in sig.parameters:
                    if param_name in modified_payload:
                        kwargs[param_name] = modified_payload[param_name]
                # Rebuild positional args from the modified payload
                new_args = []
                for i, param_name in enumerate(sig.parameters):
                    if i < len(args):
                        new_args.append(
                            modified_payload.get(param_name, args[i])
                        )
                    else:
                        break
                args = tuple(new_args) if new_args else args

            if is_async:
                return await fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # Already inside an event loop -- can't nest run_until_complete
                raise RuntimeError(
                    "Cannot call a sync @governed function from inside an "
                    "async context. Use the async version instead."
                )

            return asyncio.run(async_wrapper(*args, **kwargs))

        if is_async:
            return async_wrapper  # type: ignore[return-value]
        else:
            return sync_wrapper  # type: ignore[return-value]

    return decorator
