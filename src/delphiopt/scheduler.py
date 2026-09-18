from __future__ import annotations

from dataclasses import dataclass

from .models import SchedulingDecision
from .reputation import ExpertReputationManager


@dataclass(slots=True)
class SchedulerState:
    experts: list[str]
    difficulty: float = 0.5
    disagreement: float = 1.0
    candidate_gain: float = 1.0
    remaining_budget_ratio: float = 1.0
    completed_experts: set[str] | None = None


class Scheduler:
    strategy = "base"

    def __init__(self, *, base_tokens: int = 900, tool_budget: int = 2, reputation: ExpertReputationManager | None = None) -> None:
        self.base_tokens = base_tokens
        self.tool_budget = tool_budget
        self.reputation = reputation or ExpertReputationManager()

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        raise NotImplementedError

    def available(self, state: SchedulerState) -> list[str]:
        if not state.experts:
            raise ValueError("scheduler requires at least one expert")
        completed = state.completed_experts or set()
        return [expert for expert in state.experts if expert not in completed] or state.experts


class FixedScheduler(Scheduler):
    strategy = "fixed"

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        expert = self.available(state)[0]
        return SchedulingDecision(expert, "strong", self.strategy, self.base_tokens, self.tool_budget, 0.05, 1.0, 0.0, "fixed model and budget")


class DifficultyRouter(Scheduler):
    strategy = "difficulty"

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        expert = max(self.available(state), key=lambda item: self.reputation.weight(item))
        model = "strong" if state.difficulty >= 0.55 else "cheap"
        tokens = int(self.base_tokens * (1.5 if state.difficulty >= 0.55 else 0.75))
        return SchedulingDecision(expert, model, self.strategy, tokens, self.tool_budget, 0.08 if model == "strong" else 0.01, state.difficulty, 0.0, f"difficulty={state.difficulty:.2f}")


class AdaptiveVOIScheduler(Scheduler):
    strategy = "adaptive_voi"

    def voi(self, expert: str, state: SchedulerState) -> float:
        reliability = self.reputation.weight(expert)
        estimated_cost = 0.02 if reliability < 0.7 else 0.05
        return state.disagreement * reliability * max(0.1, state.candidate_gain) * max(0.1, state.remaining_budget_ratio) / estimated_cost

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        candidates = self.available(state)
        expert = max(candidates, key=lambda item: self.voi(item, state))
        score = self.voi(expert, state)
        model = "strong" if score >= 10 or state.difficulty > 0.7 else "cheap"
        tokens = int(self.base_tokens * (1.5 if model == "strong" else 0.8))
        cost = 0.08 if model == "strong" else 0.015
        reason = f"VOI={score:.3f}; disagreement={state.disagreement:.3f}; reliability={self.reputation.weight(expert):.3f}"
        return SchedulingDecision(expert, model, self.strategy, tokens, self.tool_budget, cost, score, score, reason)


def make_scheduler(strategy: str, *, reputation: ExpertReputationManager | None = None, base_tokens: int = 900, tool_budget: int = 2) -> Scheduler:
    normalized = strategy.lower().replace("_", "-")
    if normalized in {"fixed"}:
        return FixedScheduler(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget)
    if normalized in {"difficulty", "difficulty-router"}:
        return DifficultyRouter(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget)
    if normalized in {"adaptive-voi", "voi"}:
        return AdaptiveVOIScheduler(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget)
    raise ValueError(f"unknown scheduler strategy: {strategy}")
