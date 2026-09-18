from __future__ import annotations

import asyncio
import json
import urllib.error
from pathlib import Path
from typing import Self

from delphiopt.agents import ExpertAgent
from delphiopt.benchmark import BenchmarkEngine
from delphiopt.budget import BudgetExhausted, BudgetManager
from delphiopt.config import DEFAULT_CONFIG, load_config
from delphiopt.delphi import ConvergencePolicy, DelphiProtocol, StoppingPolicy
from delphiopt.models import AgentResponse, BudgetLimits, Proposal
from delphiopt.optimizer import CorrectnessGate, ImplementationAgent
from delphiopt.profiler import DynamicProfiler, StaticProfiler
from delphiopt.providers import HttpModelProvider, MockModelProvider, probe_model_configs, provider_from_config
from delphiopt.reputation import ExpertReputationManager
from delphiopt.sandbox import DockerSandbox, LocalSandbox, sandbox_from_config
from delphiopt.scheduler import SchedulerState, make_scheduler
from delphiopt.telemetry import RunTracer, read_events


def proposal(name: str, gain: float, support: str = "algorithm") -> Proposal:
    return Proposal(name, "hypothesis", "bottleneck", name, gain, 0.8, 0.2, 0.1, category="algorithm", source_expert=support, novelty=0.8)


def test_budget_enforces_global_limits() -> None:
    budget = BudgetManager(BudgetLimits(max_cost_usd=0.01, max_tokens=10, max_llm_calls=1))
    response = AgentResponse("ok", 4, 4, 0.01, 0.0, "m", "mock")
    budget.record_llm(response)
    assert budget.usage.total_tokens == 8
    try:
        budget.record_llm(response)
    except BudgetExhausted:
        pass
    else:
        raise AssertionError("budget should be exhausted")


def test_delphi_deduplicates_and_preserves_high_upside_minority(tmp_path: Path) -> None:
    tracer = RunTracer(tmp_path)
    protocol = DelphiProtocol(max_rounds=2)
    proposals = [proposal("set membership", 1.1), proposal("set membership", 1.1, "memory"), proposal("novel index", 1.8, "skeptic")]
    candidates = protocol.aggregate(proposals, 1, tracer)
    assert len(candidates) == 2
    assert any(item.transformation == "novel index" for item in candidates)
    assert protocol.disagreement(proposals) > 0


def test_schedulers_share_interface() -> None:
    state = SchedulerState(["algorithm", "memory"], difficulty=0.9, disagreement=0.7)
    for name in ("fixed", "difficulty", "adaptive_voi"):
        decision = make_scheduler(name).schedule(state)
        assert decision.expert_id in state.experts
        assert decision.max_tokens > 0
    adaptive = make_scheduler("adaptive_voi")
    assert adaptive.schedule(state).voi_score > 0
    difficulty = make_scheduler("difficulty")
    first = difficulty.schedule(SchedulerState(["algorithm", "memory"], completed_experts=set()))
    second = difficulty.schedule(SchedulerState(["algorithm", "memory"], completed_experts={first.expert_id}))
    assert second.expert_id != first.expert_id


def test_reputation_tracks_calibration() -> None:
    manager = ExpertReputationManager()
    item = proposal("x", 1.2)
    manager.update(item, correctness=True, actual_speedup=1.2)
    snapshot = manager.snapshot()["algorithm"]
    assert snapshot["observations"] == 1
    assert snapshot["brier_score"] >= 0
    assert abs(snapshot["calibration_error"] - 0.2) < 1e-12
    assert snapshot["prediction_error"] == 0


def test_reputation_persists_overall_and_domain_scores(tmp_path: Path) -> None:
    manager = ExpertReputationManager()
    item = proposal("x", 1.2)
    manager.update(item, correctness=True, actual_speedup=1.2)
    path = tmp_path / "reputation.json"
    manager.save(path)
    restored = ExpertReputationManager.load(path)
    assert restored.get("algorithm").observations == 1
    assert restored.weight("algorithm", "algorithm") == manager.weight("algorithm", "algorithm")


def test_mock_provider_returns_structured_proposal() -> None:
    response = asyncio.run(MockModelProvider().generate("algorithm expert", model="mock", max_tokens=100))
    assert json.loads(response.text)["expected_speedup"] > 1


def test_agent_repairs_invalid_output_and_uses_scheduled_tokens(tmp_path: Path) -> None:
    class RepairProvider:
        name = "repair"

        def __init__(self) -> None:
            self.calls: list[int] = []

        async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.2) -> AgentResponse:
            self.calls.append(max_tokens)
            text = "not json" if len(self.calls) == 1 else json.dumps(proposal("fixed", 1.2).to_dict())
            return AgentResponse(text, 3, 3, 0.0, 0.01, model, self.name)

    provider = RepairProvider()
    tracer = RunTracer(tmp_path)
    result = asyncio.run(
        ExpertAgent("algorithm", "Algorithm Expert", "repair-model", provider).analyze(
            "context", BudgetManager(), tracer, 1, max_tokens=321
        )
    )
    assert result is not None
    assert provider.calls == [321, 321]
    assert any(event["event"] == "agent_error" for event in read_events(tmp_path, tracer.run_id))


def test_agent_provider_failure_is_isolated(tmp_path: Path) -> None:
    class FailingProvider:
        name = "failing"

        async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.2) -> AgentResponse:
            raise RuntimeError("rate limited")

    tracer = RunTracer(tmp_path)
    result = asyncio.run(
        ExpertAgent("algorithm", "Algorithm Expert", "failing-model", FailingProvider()).analyze("context", BudgetManager(), tracer, 1)
    )
    assert result is None
    assert len([event for event in read_events(tmp_path, tracer.run_id) if event["event"] == "agent_error"]) == 2


def test_http_provider_response_shapes_and_factory() -> None:
    openai = HttpModelProvider("openai", "https://example.invalid", "KEY", "openai")
    anthropic = HttpModelProvider("anthropic", "https://example.invalid", "KEY", "anthropic")
    gemini = HttpModelProvider("gemini", "https://example.invalid", "KEY", "gemini")
    assert openai._extract_text({"choices": [{"message": {"content": "ok"}}]}) == "ok"
    assert anthropic._extract_text({"content": [{"text": "a"}, {"text": "b"}]}) == "ab"
    assert gemini._extract_text({"candidates": [{"content": {"parts": [{"text": "g"}]}}]}) == "g"
    assert openai._usage({"usage": {"prompt_tokens": 3, "completion_tokens": 2}}, "p", "t") == (3, 2)
    assert anthropic._usage({"usage": {"input_tokens": 4, "output_tokens": 1}}, "p", "t") == (4, 1)
    assert gemini._usage({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}, "p", "t") == (5, 2)
    assert isinstance(provider_from_config({"provider": "openai"}), HttpModelProvider)
    assert isinstance(provider_from_config({"provider": "anthropic"}), HttpModelProvider)
    assert isinstance(provider_from_config({"provider": "gemini", "model": "x"}), HttpModelProvider)


def test_http_provider_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)
    provider = HttpModelProvider("test", "https://example.invalid", "MISSING_PROVIDER_KEY", "openai")
    try:
        asyncio.run(provider.generate("hello", model="x", max_tokens=10))
    except RuntimeError as exc:
        assert "MISSING_PROVIDER_KEY" in str(exc)
    else:
        raise AssertionError("missing provider key must fail")


def test_provider_capability_probe_is_structured(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)
    results = asyncio.run(
        probe_model_configs(
            {
                "local": {"provider": "mock", "model": "mock-model"},
                "remote": {
                    "provider": "openai-compatible",
                    "model": "remote-model",
                    "endpoint": "https://example.invalid/v1/chat/completions",
                    "api_key_env": "MISSING_PROVIDER_KEY",
                },
            },
            max_concurrency=2,
        )
    )
    assert results["local"]["reachable"] is True
    assert results["local"]["structured_json"] is True
    assert results["remote"]["reachable"] is False
    assert "MISSING_PROVIDER_KEY" in str(results["remote"]["reason"])


def test_http_provider_retries_transient_failures(monkeypatch) -> None:
    attempts = 0

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"}}],"usage":{}}'

    def fake_urlopen(*args: object, **kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.URLError("temporary")
        return Response()

    monkeypatch.setenv("RETRY_KEY", "secret")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = HttpModelProvider("test", "https://example.invalid", "RETRY_KEY", "openai", max_retries=2, backoff_seconds=0)
    response = asyncio.run(provider.generate("hello", model="x", max_tokens=10))
    assert response.text == "ok"
    assert attempts == 3


def test_benchmark_collects_statistics(tmp_path: Path) -> None:
    script = tmp_path / "benchmark.py"
    script.write_text("import json; print(json.dumps({'runtime_ms': 4.0}))", encoding="utf-8")
    result = BenchmarkEngine(warmups=1, repetitions=3).run(
        "python benchmark.py", tmp_path, BudgetManager(BudgetLimits(max_benchmark_runs=10))
    )
    assert result.return_code == 0
    assert result.median_ms == 4.0
    assert len(result.samples_ms) == 3
    assert result.raw_samples_ms == [4.0, 4.0, 4.0]
    assert result.environment["python"]


def test_benchmark_compare_interleaves_and_bootstraps(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    for folder, runtime in ((baseline, 10.0), (candidate, 5.0)):
        (folder / "benchmark.py").write_text(f"import json; print(json.dumps({{'runtime_ms': {runtime}}}))", encoding="utf-8")
    budget = BudgetManager(BudgetLimits(max_benchmark_runs=20, max_tool_calls=20))
    comparison = BenchmarkEngine(warmups=1, repetitions=3, bootstrap_resamples=100).compare(
        "python benchmark.py", baseline, candidate, budget
    )
    assert comparison.speedup == 2.0
    assert comparison.ci95_low >= 2.0
    assert len(comparison.baseline.raw_samples_ms) == 3
    assert budget.usage.benchmark_runs == 8


def test_benchmark_counts_warmups_and_repetitions(tmp_path: Path) -> None:
    (tmp_path / "benchmark.py").write_text("import json; print(json.dumps({'runtime_ms': 1.0}))", encoding="utf-8")
    budget = BudgetManager(BudgetLimits(max_benchmark_runs=5, max_tool_calls=5))
    result = BenchmarkEngine(warmups=2, repetitions=3).run("python benchmark.py", tmp_path, budget)
    assert result.repetitions == 3
    assert budget.usage.benchmark_runs == 5
    assert budget.usage.tool_calls == 5


def test_benchmark_rejects_partial_evidence_when_budget_exhausts(tmp_path: Path) -> None:
    (tmp_path / "benchmark.py").write_text("import json; print(json.dumps({'runtime_ms': 1.0}))", encoding="utf-8")
    budget = BudgetManager(BudgetLimits(max_benchmark_runs=2, max_tool_calls=2))
    result = BenchmarkEngine(warmups=1, repetitions=3).run("python benchmark.py", tmp_path, budget)
    assert result.repetitions == 0
    assert "budget exhausted" in result.error


def test_benchmark_timeout_is_evidence_failure(tmp_path: Path) -> None:
    (tmp_path / "benchmark.py").write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
    result = BenchmarkEngine(warmups=0, repetitions=1, timeout_seconds=0.05).run("python benchmark.py", tmp_path)
    assert not result.samples_ms
    assert result.return_code == -1


def test_correctness_gate_stops_after_compile_failure(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "tests.py").write_text("from pathlib import Path\nPath('tests-ran').write_text('bad')\n", encoding="utf-8")
    result = CorrectnessGate().run(tmp_path, "python tests.py")
    assert not result.passed
    assert result.reason.startswith("compile failed")
    assert not (tmp_path / "tests-ran").exists()


def test_patch_and_correctness_gate(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def count_matches(values, wanted):\n    count = 0\n    for value in values:\n        if value in wanted:\n            count += 1\n    return count\n",
        encoding="utf-8",
    )
    (tmp_path / "tests.py").write_text(
        "from target import count_matches\nassert count_matches([1,2], [2]) == 1\nprint('pass')\n", encoding="utf-8"
    )
    patch = ImplementationAgent().apply(tmp_path, proposal("set membership", 1.4))
    assert patch.applied and "wanted = set(wanted)" in patch.diff
    assert CorrectnessGate().run(tmp_path, "python tests.py").passed


def test_implementation_agent_applies_validated_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    item = proposal("replace constant", 1.1)
    item.patch = "--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
    result = ImplementationAgent().apply(tmp_path, item)
    assert result.applied
    assert (tmp_path / "value.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_trace_is_jsonl_and_readable(tmp_path: Path) -> None:
    tracer = RunTracer(tmp_path, "abc")
    tracer.record("example", value=1)
    tracer.close(status="ok")
    events = read_events(tmp_path, "abc")
    assert [item["event"] for item in events] == ["run_started", "example", "run_finished"]


def test_static_profiler_finds_hot_loop(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def f(values, wanted):\n    for value in values:\n        if value in wanted: return value\n", encoding="utf-8"
    )
    findings = StaticProfiler().analyze(tmp_path)
    assert findings and findings[0].loops == 1 and findings[0].membership_checks == 1


def test_dynamic_profiler_collects_python_hotspots(tmp_path: Path) -> None:
    (tmp_path / "benchmark.py").write_text("sum(range(1000))\n", encoding="utf-8")
    profile = DynamicProfiler().profile("python benchmark.py", tmp_path, timeout_seconds=10)
    assert profile.return_code == 0
    assert profile.hotspots
    assert profile.elapsed_seconds >= 0


def test_config_returns_independent_mutable_values() -> None:
    first = load_config()
    first["budget"]["max_tokens"] = 1
    second = load_config()
    assert second["budget"]["max_tokens"] == DEFAULT_CONFIG["budget"]["max_tokens"]


def test_proposal_schema_rejects_invalid_ranges() -> None:
    data = proposal("x", 1.2).to_dict()
    data["confidence"] = 1.5
    try:
        Proposal.from_dict(data)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid confidence must be rejected")


def test_stopping_and_convergence_policies() -> None:
    assert StoppingPolicy().evaluate(expected_speedup=1.001, expected_cost_usd=0.1, remaining_budget_ratio=1)[0]
    assert ConvergencePolicy().evaluate(
        round_number=2, disagreement=0.01, ranking=("x",), previous_ranking=("x",), stagnant_rounds=1, remaining_budget_ratio=0.5
    )[0]


def test_sandbox_factory() -> None:
    assert isinstance(sandbox_from_config({"type": "local"}), LocalSandbox)
    assert isinstance(sandbox_from_config({"type": "docker"}), DockerSandbox)
