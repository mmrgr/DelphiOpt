from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from .budget import BudgetExhausted, BudgetManager
from .models import BenchmarkResult
from .sandbox import LocalSandbox


class BenchmarkEngine:
    def __init__(self, *, warmups: int = 2, repetitions: int = 5, timeout_seconds: float = 120, sandbox: LocalSandbox | None = None) -> None:
        if warmups < 0 or repetitions <= 0 or timeout_seconds <= 0:
            raise ValueError("warmups must be non-negative; repetitions and timeout must be positive")
        self.warmups = warmups
        self.repetitions = repetitions
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox or LocalSandbox()

    def run(self, command: str, cwd: str | Path, budget: BudgetManager | None = None, correctness_passed: bool = True) -> BenchmarkResult:
        for _ in range(self.warmups):
            if budget and not self._reserve(budget):
                return self._budget_failed(command, correctness_passed)
            result = self.sandbox.run(command, cwd, self.timeout_seconds)
            if budget:
                budget.record_elapsed(result.elapsed_seconds)
            if not result.ok:
                return self._failed(command, result, correctness_passed=False)
        samples: list[float] = []
        memory_mb = 0.0
        last = None
        budget_exhausted = False
        for _ in range(self.repetitions):
            if budget and not self._reserve(budget):
                budget_exhausted = True
                break
            last = self.sandbox.run(command, cwd, self.timeout_seconds)
            if budget:
                budget.record_elapsed(last.elapsed_seconds)
            if not last.ok:
                return self._failed(command, last, correctness_passed=False)
            parsed, reported_memory = self._metrics_from_output(last.stdout)
            samples.append(parsed if parsed is not None else last.elapsed_seconds * 1000)
            memory_mb = max(memory_mb, reported_memory)
        if budget_exhausted:
            return self._budget_failed(command, correctness_passed)
        if not samples:
            return self._failed(command, last, correctness_passed=False)
        mean = statistics.mean(samples)
        median = statistics.median(samples)
        stddev = statistics.stdev(samples) if len(samples) > 1 else 0.0
        margin = 1.96 * stddev / math.sqrt(len(samples)) if samples else 0.0
        return BenchmarkResult(command, median, 1000 / median if median else 0.0, memory_mb, len(samples), samples, mean, median, stddev, mean - margin, mean + margin, correctness_passed, 0, last.stdout if last else "")

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
        return BenchmarkResult(command, 0.0, 0.0, 0.0, 0, [], 0.0, 0.0, 0.0, 0.0, 0.0, correctness_passed, getattr(result, "return_code", -1), getattr(result, "stdout", ""), getattr(result, "stderr", ""))

    def _budget_failed(self, command: str, correctness_passed: bool) -> BenchmarkResult:
        return BenchmarkResult(command, 0.0, 0.0, 0.0, 0, [], 0.0, 0.0, 0.0, 0.0, 0.0, correctness_passed, -1, error="benchmark or tool budget exhausted")
