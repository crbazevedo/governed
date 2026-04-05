"""Trust evolution — earned autonomy through observed outcomes.

# Layer: Dynamic (stateful, records outcomes across invocations)

Implements Principle 3 (Earned Autonomy) and enables Principles 1 (Calibrated
Autonomy) and 2 (Masking Transparency).

Theoretical basis: Return Operator (Eq. 4) from "Minimal Oversight" (Azevedo, 2026).
Trust converges to true competence through observation and decays without evidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from governed_agents.handler import ActionContext, GovernanceHandler, GovernanceResult


@dataclass
class Outcome:
    """A recorded governance outcome."""

    action: str
    agent_id: str
    timestamp: float = field(default_factory=time.time)
    verdict: str = ""  # Pipeline verdict: "allow", "block", "modify"
    human_decision: str = ""  # "approved", "rejected", "edited", "ignored", ""
    succeeded: bool | None = None  # Did the action succeed? None = unknown yet


@dataclass
class TrustSignal:
    """Computed trust signal for an (agent, action) pair."""

    agent_id: str
    action: str
    sigma_raw: float  # Rolling raw competence (0-1)
    sigma_corr: float  # Rolling corrected quality (0-1)
    masking_index: float  # M* = sigma_corr / sigma_raw
    observation_count: int  # Total observations
    last_observed: float  # Timestamp of last observation
    recommended_vt: int | None = None  # Recommended VT tier (None = insufficient data)


@dataclass
class VTTransition:
    """A recommended VT tier change."""

    agent_id: str
    action: str
    current_vt: int
    recommended_vt: int
    direction: str  # "promote" (lower VT) or "demote" (higher VT)
    confidence: float  # 0-1, based on evidence strength
    evidence_count: int
    reason: str


class TrustLedger:
    """Records outcomes and computes earned autonomy signals.

    The ledger is the feedback loop that makes governance adaptive.
    Without it, VT tiers are static configuration. With it, agents
    earn (or lose) trust based on their track record.

    The competence estimate uses exponentially weighted observations:
    each new outcome updates sigma with weight eta, while all previous
    observations decay at rate delta. This implements the Return Operator
    dynamics from the paper.

    Note: In-memory only. For persistence across restarts, implement
    a TrustStore backend (see interfaces.py).

    Thread safety: NOT safe for concurrent access. Use external
    synchronization if multiple pipelines share a ledger.
    """

    def __init__(
        self,
        min_observations: int = 20,  # Minimum before recommending VT change
        promote_threshold: float = 0.85,  # sigma_raw above this -> recommend lower VT
        demote_threshold: float = 0.50,  # sigma_raw below this -> recommend higher VT
        decay_rate: float = 0.01,  # Per-observation decay for old evidence
        max_vt_change_per_period: int = 1,  # Max VT levels to change in one evaluation
    ) -> None:
        self._outcomes: list[Outcome] = []
        self._min_obs = min_observations
        self._promote = promote_threshold
        self._demote = demote_threshold
        self._decay = decay_rate
        self._max_change = max_vt_change_per_period

    def record(self, outcome: Outcome) -> None:
        """Record a governance outcome."""
        self._outcomes.append(outcome)

    def signal(self, agent_id: str, action: str) -> TrustSignal:
        """Compute the current trust signal for an (agent, action) pair."""
        relevant = [o for o in self._outcomes if o.agent_id == agent_id and o.action == action]

        if not relevant:
            return TrustSignal(
                agent_id=agent_id,
                action=action,
                sigma_raw=0.5,
                sigma_corr=0.5,
                masking_index=1.0,
                observation_count=0,
                last_observed=0.0,
            )

        # Compute sigma_raw: exponentially weighted success rate
        # "success" = action was allowed AND (succeeded OR was approved by human)
        sigma_raw = self._compute_sigma(relevant, corrected=False)
        sigma_corr = self._compute_sigma(relevant, corrected=True)

        if sigma_raw > 0.01:
            m_star = sigma_corr / sigma_raw
        elif sigma_corr > 0.01:
            # Agent is incompetent but human corrections mask it — extreme masking
            m_star = sigma_corr / 0.01
        else:
            # Both near zero — no masking, just bad
            m_star = 1.0

        # Recommend VT if enough evidence
        rec_vt = None
        if len(relevant) >= self._min_obs:
            if sigma_raw >= self._promote:
                rec_vt = max(0, self._sigma_to_vt(sigma_raw) - 1)  # Lower VT = more trust
            elif sigma_raw <= self._demote:
                rec_vt = min(4, self._sigma_to_vt(sigma_raw) + 1)  # Higher VT = less trust
            else:
                rec_vt = self._sigma_to_vt(sigma_raw)

        return TrustSignal(
            agent_id=agent_id,
            action=action,
            sigma_raw=round(sigma_raw, 3),
            sigma_corr=round(sigma_corr, 3),
            masking_index=round(m_star, 3),
            observation_count=len(relevant),
            last_observed=relevant[-1].timestamp,
            recommended_vt=rec_vt,
        )

    def recommend(self, agent_id: str, action: str, current_vt: int) -> VTTransition | None:
        """Recommend a VT transition based on accumulated evidence.

        Returns None if insufficient evidence or no change warranted.
        Transitions are monotonically constrained: max one level per call.
        """
        sig = self.signal(agent_id, action)

        if sig.observation_count < self._min_obs:
            return None

        if sig.recommended_vt is None or sig.recommended_vt == current_vt:
            return None

        # Constrain to max one level change
        if sig.recommended_vt < current_vt:
            new_vt = max(current_vt - self._max_change, sig.recommended_vt)
            direction = "promote"
        else:
            new_vt = min(current_vt + self._max_change, sig.recommended_vt)
            direction = "demote"

        if new_vt == current_vt:
            return None

        confidence = min(sig.observation_count / (self._min_obs * 3), 1.0)

        return VTTransition(
            agent_id=agent_id,
            action=action,
            current_vt=current_vt,
            recommended_vt=new_vt,
            direction=direction,
            confidence=round(confidence, 2),
            evidence_count=sig.observation_count,
            reason=(
                f"sigma_raw={sig.sigma_raw:.2f} over {sig.observation_count} observations. "
                f"{'Promoting' if direction == 'promote' else 'Demoting'}: "
                f"VT{current_vt} -> VT{new_vt}"
            ),
        )

    def record_incident(self, agent_id: str, action: str) -> None:
        """Record a failure incident. Adds a failed outcome that affects trust."""
        self.record(
            Outcome(
                action=action,
                agent_id=agent_id,
                verdict="block",
                human_decision="rejected",
                succeeded=False,
            )
        )

    @property
    def all_signals(self) -> list[TrustSignal]:
        """Compute trust signals for all observed (agent, action) pairs."""
        pairs = set()
        for o in self._outcomes:
            pairs.add((o.agent_id, o.action))
        return [self.signal(a, act) for a, act in sorted(pairs)]

    @property
    def masking_alerts(self) -> list[TrustSignal]:
        """Return signals where masking index exceeds 1.3 (Principle 2)."""
        return [s for s in self.all_signals if s.masking_index > 1.3 and s.observation_count >= 10]

    def _compute_sigma(self, outcomes: list[Outcome], corrected: bool) -> float:
        """Exponentially weighted competence estimate."""
        if not outcomes:
            return 0.5

        total_weight = 0.0
        weighted_sum = 0.0

        for i, o in enumerate(outcomes):
            # Exponential decay: recent observations have more weight
            age = len(outcomes) - 1 - i
            weight = (1.0 - self._decay) ** age

            # Determine success
            if corrected:
                # Corrected: did the final output succeed?
                success = 1.0 if o.succeeded is True or o.human_decision == "approved" else 0.0
            else:
                # Raw: did the agent get it right WITHOUT correction?
                if o.human_decision == "edited":
                    success = 0.0  # Human had to fix it
                elif o.human_decision == "rejected":
                    success = 0.0
                elif o.succeeded is True:
                    success = 1.0
                elif o.succeeded is False:
                    success = 0.0
                elif o.human_decision == "approved":
                    success = 1.0
                else:
                    success = 0.5  # Unknown -- neutral

            weighted_sum += weight * success
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.5

    @staticmethod
    def _sigma_to_vt(sigma: float) -> int:
        """Map sigma_raw to recommended VT tier."""
        if sigma >= 0.90:
            return 0  # VT0: highly competent
        if sigma >= 0.75:
            return 1  # VT1: competent with logging
        if sigma >= 0.55:
            return 2  # VT2: moderate, needs approval
        if sigma >= 0.35:
            return 3  # VT3: low, advisory only
        return 4  # VT4: incompetent, block


class TrustEvolutionHandler(GovernanceHandler):
    """Pipeline handler that adjusts VT tiers based on earned trust.

    Before the VTGovernanceHandler runs, this handler checks the
    TrustLedger for the (agent, action) pair and may MODIFY the
    context's vt_tier based on accumulated evidence.

    Place this handler BEFORE VTGovernanceHandler in the pipeline:
        pipeline.add(TrustEvolutionHandler(ledger))  # adjusts VT
        pipeline.add(VTGovernanceHandler())           # enforces VT
    """

    def __init__(
        self,
        ledger: TrustLedger,
        vt_floors: dict[str, int] | None = None,  # action -> minimum VT
    ) -> None:
        self._ledger = ledger
        self._floors = vt_floors or {}

    @property
    def name(self) -> str:
        return "trust_evolution"

    async def evaluate(self, context: ActionContext) -> GovernanceResult:
        sig = self._ledger.signal(context.agent_id, context.action)

        if sig.observation_count < self._ledger._min_obs:
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=(
                    f"Insufficient evidence ({sig.observation_count}/{self._ledger._min_obs}), "
                    f"keeping VT{context.vt_tier}"
                ),
            )

        rec = self._ledger.recommend(context.agent_id, context.action, context.vt_tier)

        if rec is None:
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"Trust signal sigma_raw={sig.sigma_raw:.2f} confirms VT{context.vt_tier}",
            )

        # Apply floor constraint
        floor = self._floors.get(context.action, 0)
        new_vt = max(rec.recommended_vt, floor)

        if new_vt == context.vt_tier:
            return GovernanceResult.continue_(
                handler_name=self.name,
                reason=f"Recommended VT{rec.recommended_vt} constrained by floor VT{floor}",
            )

        from dataclasses import replace

        new_meta = {
            **context.metadata,
            "trust_sigma_raw": sig.sigma_raw,
            "trust_sigma_corr": sig.sigma_corr,
            "trust_masking": sig.masking_index,
            "trust_observations": sig.observation_count,
            "trust_original_vt": context.vt_tier,
            "trust_transition": rec.direction,
        }
        modified = replace(context, vt_tier=new_vt, metadata=new_meta)

        return GovernanceResult.modify(
            modified_context=modified,
            handler_name=self.name,
            reason=rec.reason,
        )
