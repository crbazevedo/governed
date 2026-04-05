"""Core handler protocol and data types for the governance pipeline.

Defines the fundamental building blocks:
- ResultAction: outcome enum (continue, abort, modify)
- ExecutionMode: handler execution strategy (sequential, parallel)
- CallbackContext: execution context passed through the pipeline
- CallbackResult: result returned by handler checks
- CallbackHandler: abstract base class for all handlers
- HandlerRegistration: registration entry with priority, mode, dependencies
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ──────────────────────────────────────────────
# Core data types
# ──────────────────────────────────────────────


class ResultAction(str, Enum):
    """Outcome of a handler check."""

    CONTINUE = "continue"  # Pipeline proceeds to next handler
    ABORT = "abort"        # Pipeline halts, action is blocked
    MODIFY = "modify"      # Pipeline proceeds with modified context


class ExecutionMode(str, Enum):
    """How handlers in the same priority group are executed."""

    SEQUENTIAL = "sequential"  # Runs after previous handler completes
    PARALLEL = "parallel"      # Runs concurrently with other parallel handlers


@dataclass
class CallbackContext:
    """Execution context passed through the pipeline.

    Carries the action being evaluated, agent identity, VT tier,
    and an extensible metadata dict for handler-to-handler communication.
    """

    action: str                          # The action being evaluated (e.g., tool name)
    agent_id: str = ""                   # Source agent identity
    vt_tier: int = 0                     # VT risk tier for the action
    payload: dict[str, Any] = field(default_factory=dict)  # Action payload
    metadata: dict[str, Any] = field(default_factory=dict)  # Handler-to-handler data


@dataclass
class CallbackResult:
    """Result returned by a handler check."""

    action: ResultAction
    reason: str = ""
    handler_name: str = ""
    modified_context: CallbackContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def continue_(cls, handler_name: str = "", reason: str = "") -> CallbackResult:
        """Factory for a CONTINUE result."""
        return cls(action=ResultAction.CONTINUE, handler_name=handler_name, reason=reason)

    @classmethod
    def abort(cls, handler_name: str = "", reason: str = "") -> CallbackResult:
        """Factory for an ABORT result."""
        return cls(action=ResultAction.ABORT, handler_name=handler_name, reason=reason)

    @classmethod
    def modify(
        cls, modified_context: CallbackContext, handler_name: str = "", reason: str = ""
    ) -> CallbackResult:
        """Factory for a MODIFY result (context transformation)."""
        return cls(
            action=ResultAction.MODIFY,
            handler_name=handler_name,
            reason=reason,
            modified_context=modified_context,
        )


# ──────────────────────────────────────────────
# Handler protocol
# ──────────────────────────────────────────────


class CallbackHandler(ABC):
    """Abstract base for pipeline handlers.

    Each handler implements check() which evaluates the context and returns
    a CallbackResult (continue, abort, or modify).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this handler (used in logging and dependencies)."""
        ...

    @abstractmethod
    async def check(self, context: CallbackContext) -> CallbackResult:
        """Evaluate the context and return a result.

        Args:
            context: The current pipeline context.

        Returns:
            CallbackResult indicating whether to continue, abort, or modify.
        """
        ...


# ──────────────────────────────────────────────
# Handler registration
# ──────────────────────────────────────────────


@dataclass
class HandlerRegistration:
    """Registration entry for a handler in the pipeline.

    Attributes:
        handler: The callback handler instance.
        priority: Execution order group (lower runs first).
        mode: Sequential or parallel execution within the group.
        optional: If True, failure is logged but does not affect the verdict.
        depends_on: Handler names that must complete before this handler runs.
                    If any dependency hasn't completed in an earlier group,
                    the handler is deferred to the next priority group.
    """

    handler: CallbackHandler
    priority: int = 100
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    optional: bool = False
    depends_on: frozenset[str] = frozenset()
