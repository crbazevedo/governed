"""Structured recovery for blocked governance actions.

# Layer: Static (stateless types and enums)

Implements Principle 5 (Graceful Degradation). When governance blocks an action,
the system provides typed recovery paths that agents can programmatically attempt,
not just human-readable strings.

Theoretical basis: AMO scope selection -- partial delegation at high quality
beats full delegation at low quality. Recovery should narrow scope or shift
strategy, not just retry blindly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RecoveryAction(str, Enum):
    """Typed recovery strategies for blocked actions."""

    RETRY_WITH_APPROVAL = "retry_with_approval"
    RETRY_LOWER_SCOPE = "retry_lower_scope"
    RETRY_AFTER_DELAY = "retry_after_delay"
    DELEGATE_TO_HUMAN = "delegate_to_human"
    DOWNGRADE_TO_ADVISORY = "downgrade_to_advisory"
    BATCH_WITH_OTHERS = "batch_with_others"
    USE_CHEAPER_RESOURCE = "use_cheaper_resource"
    SPLIT_ACTION = "split_action"


@dataclass
class RecoveryPlan:
    """Structured recovery plan attached to BLOCK verdicts.

    The primary action is the system's best recommendation.
    Alternatives are ranked by likelihood of success.
    Context carries action-specific data needed for recovery.
    """

    primary: RecoveryAction
    alternatives: list[RecoveryAction] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    @property
    def all_actions(self) -> list[RecoveryAction]:
        """Primary + alternatives in priority order."""
        return [self.primary] + self.alternatives

    def has(self, action: RecoveryAction) -> bool:
        """Check if a specific recovery action is available."""
        return action in self.all_actions
