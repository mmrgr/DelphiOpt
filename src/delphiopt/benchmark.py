from __future__ import annotations

import json
import math
import os
import platform
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from .budget import BudgetExhausted, BudgetManager
from .models import BenchmarkResult
from .sandbox import CommandResult, LocalSandbox


@dataclass(slots=True)
class BenchmarkComparison:
    baseline: BenchmarkResult
    candidate: BenchmarkResult
    speedup: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "speedup": self.speedup,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


class BenchmarkEngine:
    def __init__(
        self,
        *,
        warmups: int = 2,
        repetitions: int = 7,
        timeout_seconds: float = 120,
        sandbox: LocalSandbox | None = None,
        seed: int = 0,
        bootstrap_resamples: int = 2000,
        cpu_affinity: list[int] | None = None,
    ) -> None:
        if warmups < 0 or repetitions <= 0 or timeout_seconds <= 0 or bootstrap_resamples <= 0:
            raise ValueError("warmups must be non-negative; repetitions, timeout, and bootstrap resamples must be positive")
        self.warmups = warmups
        self.repetitions = repetitions
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox or LocalSandbox()
        self.seed = seed
        self.bootstrap_resamples = bootstrap_resamples
        self.cpu_affinity = cpu_affinity or []

    def run(self, command: str, cwd: str | Path, budget: BudgetManager | None = None, correctness_passed: bool = True) -> BenchmarkResult:
        for _ in range(self.warmups):
            result = self._run_once(command, cwd, budget)
            if result is None:
                return self._budget_failed(command, correctness_passed)
            if not result.ok:
                return self._failed(command, result, correctness_passed=False)
        samples: list[float] = []
        memory_mb = 0.0
        last: CommandResult | None = None
        for _ in range(self.repetitions):
            last = self._run_once(command, cwd, budget)
            if last is None:
                return self._budget_failed(command, correctness_passed)
            if not last.ok:
                return self._failed(command, last, correctness_passed=False)
            sample, reported_memory = self._sample(last)
            samples.append(sample)
            memory_mb = max(memory_mb, reported_memory)
        return self._summarize(command, samples, memory_mb, correctness_passed, last)

    def compare(
        self,
        command: str,
        baseline_cwd: str | Path,
        candidate_cwd: str | Path,
        budget: BudgetManager | None = None,
        correctness_passed: bool = True,
    ) -> BenchmarkComparison:
        """Randomly interleave baseline and candidate runs, then bootstrap speedup."""
        rng = random.Random(self.seed)
        for cwd in (baseline_cwd, candidate_cwd):
            for _ in range(min(1, self.warmups)):
                warmup = self._run_once(command, cwd, budget)
                if warmup is None or not warmup.ok:
                    failed = self._budget_failed(command, correctness_passed) if warmup is None else self._failed(command, warmup, False)
                    return BenchmarkComparison(failed, failed, 0.0, 0.0, 0.0)

        labels = ["baseline", "candidate"] * self.repetitions
        rng.shuffle(labels)
        samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
        memory = {"baseline": 0.0, "candidate": 0.0}
        last: dict[str, CommandResult | None] = {"baseline": None, "candidate": None}
        paths = {"baseline": baseline_cwd, "candidate": candidate_cwd}
        for label in labels:
            result = self._run_once(command, paths[label], budget)
            if result is None or not result.ok:
                failed = self._budget_failed(command, correctness_passed) if result is None else self._failed(command, result, False)
                return BenchmarkComparison(failed, failed, 0.0, 0.0, 0.0)
            sample, reported_memory = self._sample(result)
            samples[label].append(sample)
            memory[label] = max(memory[label], reported_memory)
            last[label] = result

        baseline = self._summarize(command, samples["baseline"], memory["baseline"], correctness_passed, last["baseline"])
        candidate = self._summarize(command, samples["candidate"], memory["candidate"], correctness_passed, last["candidate"])
        ratios = self._bootstrap_speedups(baseline.samples_ms, candidate.samples_ms)
        speedup = baseline.median_ms / candidate.median_ms if candidate.median_ms else 0.0
        return BenchmarkComparison(baseline, candidate, speedup, _percentile(ratios, 0.025), _percentile(ratios, 0.975))

    def _run_once(self, command: str, cwd: str | Path, budget: BudgetManager | None) -> CommandResult | None:
        if budget and not self._reserve(budget):
            return None
        result = self.sandbox.run(self._affinity_command(command), cwd, self.timeout_seconds)
        if budget:
            budget.record_elapsed(result.elapsed_seconds)
        return result

    def _affinity_command(self, command: str) -> str:
        if not self.cpu_affinity:
            return command
        cores = ",".join(str(core) for core in self.cpu_affinity)
        if os.name == "posix" and platform.system() == "Linux":
            return f"taskset -c {cores} {command}"
        return command

    def _sample(self, result: CommandResult) -> tuple[float, float]:
        parsed, memory_mb = self._metrics_from_output(result.stdout)
        return (parsed if parsed is not None else result.elapsed_seconds * 1000), memory_mb

    def _summarize(
        self,
        command: str,
        raw_samples: list[float],
        memory_mb: float,
        correctness_passed: bool,
        last: CommandResult | None,
    ) -> BenchmarkResult:
        samples, excluded = _reject_outliers(raw_samples)
        mean = statistics.mean(samples)
        median = statistics.median(samples)
        stddev = statistics.stdev(samples) if len(samples) > 1 else 0.0
        means = self._bootstrap_means(samples)
        return BenchmarkResult(
            command,
            median,
            1000 / median if median else 0.0,
            memory_mb,
            len(samples),
            samples,
            mean,
            median,
            stddev,
            _percentile(means, 0.025),
            _percentile(means, 0.975),
            correctness_passed,
            0,
            last.stdout if last else "",
            raw_samples_ms=list(raw_samples),
            excluded_samples_ms=excluded,
            environment=_environment(),
        )

    def _bootstrap_means(self, samples: list[float]) -> list[float]:
        rng = random.Random(self.seed)
        return [statistics.mean(rng.choices(samples, k=len(samples))) for _ in range(self.bootstrap_resamples)]

    def _bootstrap_speedups(self, baseline: list[float], candidate: list[float]) -> list[float]:
        if not baseline or not candidate:
            return [0.0]
        rng = random.Random(self.seed)
        ratios: list[float] = []
        for _ in range(self.bootstrap_resamples):
            baseline_median = statistics.median(rng.choices(baseline, k=len(baseline)))
            candidate_median = statistics.median(rng.choices(candidate, k=len(candidate)))
            ratios.append(baseline_median / candidate_median if candidate_median else 0.0)
        return sorted(ratios)

    def _reserve(self, budget: BudgetManager) -> bool:
        try:
            budget.reserve_tool(benchmark=True)
            return True
        except BudgetExhausted:
            return False

    def _metrics_from_output(self, output: str) -> tuple[float | None, float]:
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
                if isinstance(value, dict) and "runtime_ms" in value:
                    return float(value["runtime_ms"]), float(value.get("memory_mb", 0.0))
            except (ValueError, TypeError):
                continue
        return None, 0.0

    def _failed(self, command: str, result: object | None, correctness_passed: bool) -> BenchmarkResult:
        return BenchmarkResult(
            command,
            0.0,
            0.0,
            0.0,
            0,
            [],
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            correctness_passed,
            getattr(result, "return_code", -1),
            getattr(result, "stdout", ""),
            getattr(result, "stderr", ""),
            environment=_environment(),
        )

    def _budget_failed(self, command: str, correctness_passed: bool) -> BenchmarkResult:
        return BenchmarkResult(
            command,
            0.0,
            0.0,
            0.0,
            0,
            [],
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            correctness_passed,
            -1,
            error="benchmark or tool budget exhausted",
            environment=_environment(),
        )


def _reject_outliers(samples: list[float]) -> tuple[list[float], list[float]]:
    if len(samples) < 5:
        return list(samples), []
    median = statistics.median(samples)
    deviations = [abs(sample - median) for sample in samples]
    mad = statistics.median(deviations)
    if mad == 0:
        return list(samples), []
    threshold = 3.5 * 1.4826 * mad
    kept = [sample for sample in samples if abs(sample - median) <= threshold]
    excluded = [sample for sample in samples if abs(sample - median) > threshold]
    return (kept or list(samples)), excluded


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count": str(os.cpu_count() or "unknown"),
    }
