from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any


@dataclass(slots=True)
class Proposal:
    id: str
    hypothesis: str
    bottleneck: str
    transformation: str
    expected_speedup: float
    confidence: float
    implementation_cost: float
    correctness_risk: float
    memory_risk: float = 0.0
    evidence_required: list[str] = field(default_factory=list)
    category: str = "general"
    author_anonymous_id: str = "anonymous"
    novelty: float = 0.5
    source_expert: str = "unknown"
    patch: str = ""

    def normalized_key(self) -> str:
        return " ".join(self.transformation.lower().split())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_id: str = "proposal") -> Proposal:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        values = {key: value for key, value in data.items() if key in fields}
        values.setdefault("id", fallback_id)
        values.setdefault("hypothesis", "")
        values.setdefault("bottleneck", "")
        values.setdefault("transformation", "")
        for key in ("id", "hypothesis", "bottleneck", "transformation"):
            values[key] = str(values.get(key, "")).strip()
            if not values[key]:
                raise ValueError(f"proposal.{key} must not be empty")
        for key in ("expected_speedup", "confidence", "implementation_cost", "correctness_risk", "memory_risk", "novelty"):
            values[key] = float(values.get(key, 0.0))
            if not isfinite(values[key]):
                raise ValueError(f"proposal.{key} must be finite")
        if values["expected_speedup"] <= 0:
            raise ValueError("proposal.expected_speedup must be positive")
        for key in ("confidence", "implementation_cost", "correctness_risk", "memory_risk", "novelty"):
            if not 0 <= values[key] <= 1:
                raise ValueError(f"proposal.{key} must be between 0 and 1")
        evidence = values.get("evidence_required") or []
        values["evidence_required"] = [str(item) for item in (evidence if isinstance(evidence, list) else [evidence])]
        values["patch"] = str(values.get("patch", ""))
        return cls(**values)


@dataclass(slots=True)
class BenchmarkResult:
    command: str
    runtime_ms: float
    throughput: float
    memory_mb: float
    repetitions: int
    samples_ms: list[float]
    mean_ms: float
    median_ms: float
    stddev_ms: float
    ci95_low_ms: float
    ci95_high_ms: float
    correctness_passed: bool
    return_code: int
    output: str = ""
    error: str = ""
    raw_samples_ms: list[float] = field(default_factory=list)
    excluded_samples_ms: list[float] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SchedulingDecision:
    expert_id: str
    model: str
    strategy: str
    max_tokens: int
    tool_budget: int
    cost_budget: float
    priority: float
    voi_score: float
    reason: str
    action: str = "ask"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BudgetLimits:
    max_cost_usd: float = 1.0
    max_tokens: int = 150_000
    max_latency_seconds: float = 900.0
    max_llm_calls: int = 30
    max_benchmark_runs: int = 20
    max_tool_calls: int = 100


@dataclass(slots=True)
class BudgetUsage:
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    tool_calls: int = 0
    benchmark_runs: int = 0
    llm_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


@dataclass(slots=True)
class AgentResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_seconds: float
    model: str
    provider: str


@dataclass(slots=True)
class RunSummary:
    run_id: str
    project: str
    status: str
    baseline_ms: float
    best_ms: float
    speedup: float
    correctness: bool
    rounds: int
    candidates_evaluated: int
    winning_proposal: str = ""
    stop_reason: str = ""
    cost_usd: float = 0.0
    total_tokens: int = 0
    proposal_diversity: float = 0.0
    latency_seconds: float = 0.0
    llm_calls: int = 0
    benchmark_runs: int = 0
    tool_calls: int = 0
    verified_speedup_per_dollar: float = 0.0
    round_disagreements: list[float] = field(default_factory=list)
    models_used: dict[str, int] = field(default_factory=dict)
    expert_reliability: dict[str, float] = field(default_factory=dict)
    calibration_error: float = 0.0
    prediction_error: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
