"""Core handler protocol and data types for the governance pipeline.

# Layer: Static (stateless types, no external dependencies)

Defines the fundamental building blocks:
- Verdict: outcome enum (allow, block, modify)
- ExecutionMode: handler execution strategy (sequential, parallel)
- ActionContext: execution context passed through the pipeline
- GovernanceResult: result returned by handler evaluations
- GovernanceHandler: abstract base class for all handlers
- HandlerRegistration: registration entry with priority, mode, dependencies
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from governed_agents.recovery import RecoveryPlan


# ──────────────────────────────────────────────
# Core data types
# ──────────────────────────────────────────────


class Verdict(str, Enum):
    """Outcome of a handler evaluation."""

    ALLOW = "allow"  # Pipeline proceeds to next handler
    BLOCK = "block"  # Pipeline halts, action is blocked
    MODIFY = "modify"  # Pipeline proceeds with modified context


class ExecutionMode(str, Enum):
    """How handlers in the same priority group are executed."""

    SEQUENTIAL = "sequential"  # Runs after previous handler completes
    PARALLEL = "parallel"  # Runs concurrently with other parallel handlers


@dataclass
class ActionContext:
    """Execution context passed through the pipeline.

    Carries the action being evaluated, agent identity, VT tier,
    and an extensible metadata dict for handler-to-handler communication.
    """

    action: str  # The action being evaluated (e.g., tool name)
    agent_id: str = ""  # Source agent identity
    vt_tier: int = 1  # VT risk tier for the action
    payload: dict[str, Any] = field(default_factory=dict)  # Action payload
    metadata: dict[str, Any] = field(default_factory=dict)  # Handler-to-handler data

    @property
    def agent_name(self) -> str:
        """Backward-compatible alias for agent_id."""
        return self.agent_id


@dataclass
class GovernanceResult:
    """Result returned by a handler evaluation.

    For BLOCK results, ``suggestion`` and ``alternatives`` provide structured
    recovery guidance that enables agents to self-repair -- adjusting their
    approach rather than simply failing.  This beats opaque reason strings
    because downstream code can programmatically inspect the alternatives
    list and attempt automatic recovery.
    """

    action: Verdict
    reason: str = ""
    handler_name: str = ""
    modified_context: ActionContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    """Actionable fix hint -- tells the agent exactly what to do to unblock."""
    alternatives: list[str] = field(default_factory=list)
    """Concrete things the agent could try instead of the blocked action."""
    recovery: RecoveryPlan | None = None
    """Typed, programmatic recovery plan for BLOCK verdicts.

    While ``suggestion`` and ``alternatives`` are human-readable strings kept
    for backward compatibility, ``recovery`` provides a typed vocabulary that
    agent frameworks can act on programmatically.
    """

    @classmethod
    def continue_(cls, handler_name: str = "", reason: str = "") -> GovernanceResult:
        """Factory for an ALLOW result."""
        return cls(action=Verdict.ALLOW, handler_name=handler_name, reason=reason)

    @classmethod
    def abort(
        cls,
        handler_name: str = "",
        reason: str = "",
        suggestion: str = "",
        alternatives: list[str] | None = None,
        recovery: RecoveryPlan | None = None,
    ) -> GovernanceResult:
        """Factory for a BLOCK result with structured recovery guidance.

        Args:
            handler_name: Name of the handler that blocked the action.
            reason: Human-readable explanation of why the action was blocked.
            suggestion: Actionable hint for how the agent can fix the issue
                        and retry successfully.
            alternatives: List of concrete alternative approaches the agent
                          could take instead.
            recovery: Typed recovery plan for programmatic self-repair.
                      Complements the human-readable suggestion/alternatives.
        """
        return cls(
            action=Verdict.BLOCK,
            handler_name=handler_name,
            reason=reason,
            suggestion=suggestion,
            alternatives=alternatives or [],
            recovery=recovery,
        )

    @classmethod
    def modify(
        cls, modified_context: ActionContext, handler_name: str = "", reason: str = ""
    ) -> GovernanceResult:
        """Factory for a MODIFY result (context transformation)."""
        return cls(
            action=Verdict.MODIFY,
            handler_name=handler_name,
            reason=reason,
            modified_context=modified_context,
        )


# ──────────────────────────────────────────────
# Handler protocol
# ──────────────────────────────────────────────


class GovernanceHandler(ABC):
    """Abstract base for pipeline handlers.

    Each handler implements evaluate() which evaluates the context and returns
    a GovernanceResult (allow, block, or modify).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this handler (used in logging and dependencies)."""
        ...

    @abstractmethod
    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        """Evaluate the context and return a result.

        Args:
            context: The current pipeline context.

        Returns:
            GovernanceResult indicating whether to allow, block, or modify.
        """
        ...

    async def check(self, context: ActionContext) -> GovernanceResult:
        """Backward-compatible alias for evaluate()."""
        return await self.evaluate(context)


# ──────────────────────────────────────────────
# Handler registration
# ──────────────────────────────────────────────


@dataclass
class HandlerRegistration:
    """Registration entry for a handler in the pipeline.

    Attributes:
        handler: The governance handler instance.
        priority: Execution order group (lower runs first).
        mode: Sequential or parallel execution within the group.
        optional: If True, failure is logged but does not affect the verdict.
        depends_on: Handler names that must complete before this handler runs.
                    If any dependency hasn't completed in an earlier group,
                    the handler is deferred to the next priority group.
    """

    handler: GovernanceHandler
    priority: int = 100
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    optional: bool = False
    depends_on: frozenset[str] = frozenset()


# ──────────────────────────────────────────────
# Backward-compatible aliases (not exported in __init__.py)
# ──────────────────────────────────────────────

ResultAction = Verdict
CallbackContext = ActionContext
CallbackResult = GovernanceResult
CallbackHandler = GovernanceHandler
