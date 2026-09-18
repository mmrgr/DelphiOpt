from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import Proposal
from .reputation import ExpertReputationManager
from .telemetry import RunTracer


@dataclass(slots=True)
class DelphiRound:
    number: int
    proposals: list[Proposal]
    candidates: list[Proposal]
    disagreement: float


@dataclass(slots=True)
class CandidateWeights:
    consensus: float = 0.25
    expected_gain: float = 0.25
    confidence: float = 0.20
    novelty: float = 0.12
    reputation: float = 0.10
    implementation_cost: float = 0.05
    correctness_risk: float = 0.03


@dataclass(slots=True)
class ConvergencePolicy:
    disagreement_threshold: float = 0.08
    max_rounds: int = 3
    no_improvement_rounds: int = 2

    def evaluate(
        self,
        *,
        round_number: int,
        disagreement: float,
        ranking: tuple[str, ...],
        previous_ranking: tuple[str, ...],
        stagnant_rounds: int,
        remaining_budget_ratio: float,
    ) -> tuple[bool, str]:
        if remaining_budget_ratio <= 0:
            return True, "global budget exhausted"
        if round_number >= self.max_rounds:
            return True, "max rounds reached"
        if previous_ranking and ranking == previous_ranking and disagreement < self.disagreement_threshold:
            return True, "proposal ranking converged"
        if stagnant_rounds >= self.no_improvement_rounds:
            return True, "no verified improvement across rounds"
        return False, "continue"


@dataclass(slots=True)
class StoppingPolicy:
    marginal_gain_threshold: float = 0.02
    min_utility_per_usd: float = 0.1

    def evaluate(self, *, expected_speedup: float, expected_cost_usd: float, remaining_budget_ratio: float) -> tuple[bool, str]:
        gain = max(0.0, expected_speedup - 1.0)
        if remaining_budget_ratio <= 0:
            return True, "global budget exhausted"
        if gain < self.marginal_gain_threshold:
            return True, "expected marginal gain below threshold"
        utility = gain / max(expected_cost_usd, 1e-6)
        if utility < self.min_utility_per_usd:
            return True, "expected utility per dollar below threshold"
        return False, "continue"


class DelphiProtocol:
    """Reusable independent elicitation -> anonymous feedback -> revision protocol."""

    def __init__(
        self,
        *,
        reputation: ExpertReputationManager | None = None,
        max_rounds: int = 3,
        disagreement_threshold: float = 0.08,
        minority_bonus: float = 0.12,
        weights: CandidateWeights | None = None,
    ) -> None:
        self.reputation = reputation or ExpertReputationManager()
        self.max_rounds = max_rounds
        self.disagreement_threshold = disagreement_threshold
        self.minority_bonus = minority_bonus
        self.weights = weights or CandidateWeights()
        self.rounds: list[DelphiRound] = []

    def aggregate(self, proposals: list[Proposal], round_number: int, tracer: RunTracer) -> list[Proposal]:
        if not proposals:
            return []
        groups: dict[str, list[Proposal]] = {}
        for proposal in proposals:
            groups.setdefault(proposal.normalized_key(), []).append(proposal)
        candidates: list[Proposal] = []
        for members in groups.values():
            representative = max(members, key=lambda item: self.score(item, len(members), len(proposals)))
            candidates.append(representative)
        candidates.sort(
            key=lambda item: self.score(item, sum(p.normalized_key() == item.normalized_key() for p in proposals), len(proposals)),
            reverse=True,
        )
        disagreement = self.disagreement(proposals)
        tracer.record(
            "anonymous_aggregation",
            round=round_number,
            proposal_count=len(proposals),
            candidate_count=len(candidates),
            disagreement=disagreement,
            proposal_diversity=self.diversity(proposals),
            candidates=[p.to_dict() for p in candidates],
        )
        return candidates

    def score(self, proposal: Proposal, support: int, total: int) -> float:
        consensus = support / max(1, total)
        minority = (
            self.minority_bonus
            if support / max(1, total) < 0.4 and proposal.expected_speedup >= 1.2 and proposal.correctness_risk < 0.35
            else 0.0
        )
        weights = self.weights
        return (
            weights.consensus * consensus
            + weights.expected_gain * min(2.0, proposal.expected_speedup) / 2
            + weights.confidence * proposal.confidence
            + weights.novelty * proposal.novelty
            + weights.reputation * self.reputation.weight(proposal.source_expert, proposal.category)
            + minority
            - weights.implementation_cost * proposal.implementation_cost
            - weights.correctness_risk * proposal.correctness_risk
        )

    @staticmethod
    def disagreement(proposals: list[Proposal]) -> float:
        if len(proposals) < 2:
            return 0.0
        values = [proposal.expected_speedup for proposal in proposals]
        mean = statistics.mean(values)
        return statistics.pstdev(values) / max(0.01, mean)

    @staticmethod
    def diversity(proposals: list[Proposal]) -> float:
        return len({proposal.normalized_key() for proposal in proposals}) / max(1, len(proposals))

    def feedback(self, candidates: list[Proposal], evidence: str) -> str:
        lines = ["Anonymous proposal feedback; do not infer author identity:"]
        for index, candidate in enumerate(candidates, 1):
            lines.append(
                f"Candidate {index}: transformation={candidate.transformation}; expected={candidate.expected_speedup:.2f}; confidence={candidate.confidence:.2f}"
            )
        lines.append(f"Observed evidence: {evidence}")
        return "\n".join(lines)
