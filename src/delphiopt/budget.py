from __future__ import annotations

from dataclasses import asdict

from .models import AgentResponse, BudgetLimits, BudgetUsage


class BudgetExhausted(RuntimeError):
    """Raised when a global budget cannot cover the next operation."""


class BudgetManager:
    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self.limits = limits or BudgetLimits()
        self.usage = BudgetUsage()

    def can_afford(self, *, cost: float = 0.0, tokens: int = 0, latency: float = 0.0) -> bool:
        usage, limits = self.usage, self.limits
        return (
            usage.cost_usd + cost <= limits.max_cost_usd
            and usage.total_tokens + tokens <= limits.max_tokens
            and usage.elapsed_seconds + latency <= limits.max_latency_seconds
            and usage.llm_calls < limits.max_llm_calls
        )

    def record_llm(self, response: AgentResponse) -> None:
        self.usage.cost_usd += response.cost_usd
        self.usage.input_tokens += response.input_tokens
        self.usage.output_tokens += response.output_tokens
        self.usage.elapsed_seconds += response.latency_seconds
        self.usage.llm_calls += 1
        limits = self.limits
        if self.usage.cost_usd > limits.max_cost_usd or self.usage.total_tokens > limits.max_tokens or self.usage.elapsed_seconds > limits.max_latency_seconds or self.usage.llm_calls > limits.max_llm_calls:
            raise BudgetExhausted("global LLM budget exhausted after recording actual usage")

    def record_tool(self) -> None:
        self.reserve_tool()

    def reserve_tool(self, *, benchmark: bool = False) -> None:
        if self.usage.tool_calls >= self.limits.max_tool_calls:
            raise BudgetExhausted("global tool-call budget exhausted")
        if self.usage.elapsed_seconds >= self.limits.max_latency_seconds:
            raise BudgetExhausted("global latency budget exhausted")
        if benchmark and self.usage.benchmark_runs >= self.limits.max_benchmark_runs:
            raise BudgetExhausted("global benchmark budget exhausted")
        self.usage.tool_calls += 1
        if benchmark:
            self.usage.benchmark_runs += 1

    def record_elapsed(self, seconds: float) -> None:
        self.usage.elapsed_seconds += max(0.0, seconds)

    def record_benchmark(self) -> None:
        if self.usage.benchmark_runs >= self.limits.max_benchmark_runs:
            raise BudgetExhausted("global benchmark budget exhausted")
        self.usage.benchmark_runs += 1

    def remaining_ratio(self) -> float:
        limits = self.limits
        remaining = (
            1 - self.usage.cost_usd / max(limits.max_cost_usd, 1e-9),
            1 - self.usage.total_tokens / max(limits.max_tokens, 1),
            1 - self.usage.elapsed_seconds / max(limits.max_latency_seconds, 1e-9),
            1 - self.usage.llm_calls / max(limits.max_llm_calls, 1),
            1 - self.usage.tool_calls / max(limits.max_tool_calls, 1),
            1 - self.usage.benchmark_runs / max(limits.max_benchmark_runs, 1),
        )
        return max(0.0, min(remaining))

    def snapshot(self) -> dict[str, object]:
        return {"limits": asdict(self.limits), "usage": self.usage.to_dict()}
