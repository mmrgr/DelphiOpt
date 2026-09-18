from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    model_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    minimum_experts: int = 2


class Scheduler:
    strategy = "base"

    def __init__(
        self,
        *,
        base_tokens: int = 900,
        tool_budget: int = 2,
        reputation: ExpertReputationManager | None = None,
        models: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.base_tokens = base_tokens
        self.tool_budget = tool_budget
        self.reputation = reputation or ExpertReputationManager()
        self.models = models or {}

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        raise NotImplementedError

    def available(self, state: SchedulerState) -> list[str]:
        if not state.experts:
            raise ValueError("scheduler requires at least one expert")
        completed = state.completed_experts or set()
        return [expert for expert in state.experts if expert not in completed] or state.experts

    def estimated_cost(self, model: str, max_tokens: int) -> float:
        profile = self.models.get(model, {})
        input_price = float(profile.get("input_price_per_million", 0.0))
        output_price = float(profile.get("output_price_per_million", 0.0))
        return max_tokens / 1_000_000 * (input_price + output_price)


class FixedScheduler(Scheduler):
    strategy = "fixed"

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        expert = self.available(state)[0]
        return SchedulingDecision(
            expert,
            "strong",
            self.strategy,
            self.base_tokens,
            self.tool_budget,
            self.estimated_cost("strong", self.base_tokens),
            1.0,
            0.0,
            "fixed model and budget",
        )


class DifficultyRouter(Scheduler):
    strategy = "difficulty"

    def schedule(self, state: SchedulerState) -> SchedulingDecision:
        expert = max(self.available(state), key=lambda item: self.reputation.weight(item))
        model = "strong" if state.difficulty >= 0.55 else "cheap"
        tokens = int(self.base_tokens * (1.5 if state.difficulty >= 0.55 else 0.75))
        action = "escalate" if model == "strong" else "ask"
        return SchedulingDecision(
            expert,
            model,
            self.strategy,
            tokens,
            self.tool_budget,
            self.estimated_cost(model, tokens),
            state.difficulty,
            0.0,
            f"difficulty={state.difficulty:.2f}",
            action,
        )


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
        completed = len(state.completed_experts or set())
        if state.remaining_budget_ratio <= 0.03:
            return SchedulingDecision(expert, "cheap", self.strategy, 0, 0, 0.0, 0.0, score, "remaining budget is below 3%", "stop")
        if completed >= state.minimum_experts and (state.disagreement < 0.12 or state.candidate_gain < 0.03):
            return SchedulingDecision(
                expert, "cheap", self.strategy, 0, 0, 0.0, 0.0, score, "enough evidence; marginal value is low", "stop"
            )
        if completed and self.reputation.weight(expert) < 0.35:
            return SchedulingDecision(expert, "cheap", self.strategy, 0, 0, 0.0, 0.0, score, "historical reliability is below 0.35", "skip")
        model = "strong" if score >= 10 or state.difficulty > 0.7 else "cheap"
        action = "escalate" if model == "strong" else "ask"
        tokens = int(self.base_tokens * (1.5 if action == "escalate" else 0.8) * max(0.35, state.remaining_budget_ratio))
        stats = state.model_stats.get(model, {})
        success_rate = stats.get("successes", 0.0) / max(1.0, stats.get("calls", 0.0))
        latency = stats.get("latency_seconds", 0.0) / max(1.0, stats.get("calls", 0.0))
        cost = self.estimated_cost(model, tokens)
        reason = (
            f"VOI={score:.3f}; disagreement={state.disagreement:.3f}; "
            f"reliability={self.reputation.weight(expert):.3f}; historical_success={success_rate:.3f}; "
            f"historical_latency={latency:.3f}s; estimated_cost=${cost:.6f}"
        )
        return SchedulingDecision(expert, model, self.strategy, tokens, self.tool_budget, cost, score, score, reason, action)


def make_scheduler(
    strategy: str,
    *,
    reputation: ExpertReputationManager | None = None,
    base_tokens: int = 900,
    tool_budget: int = 2,
    models: dict[str, dict[str, Any]] | None = None,
) -> Scheduler:
    normalized = strategy.lower().replace("_", "-")
    if normalized in {"fixed"}:
        return FixedScheduler(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget, models=models)
    if normalized in {"difficulty", "difficulty-router"}:
        return DifficultyRouter(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget, models=models)
    if normalized in {"adaptive-voi", "voi"}:
        return AdaptiveVOIScheduler(reputation=reputation, base_tokens=base_tokens, tool_budget=tool_budget, models=models)
    raise ValueError(f"unknown scheduler strategy: {strategy}")
