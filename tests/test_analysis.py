from __future__ import annotations

from pathlib import Path

from analysis.run_suite import METHODS, _aggregate, task_projects


def test_benchmark_suite_has_dozen_scale_coverage() -> None:
    tasks = task_projects(Path(__file__).parents[1] / "benchmarks" / "tasks", None)
    assert len(tasks) >= 30
    assert len(METHODS) >= 6
    assert {mode for mode, _ in METHODS} >= {"single", "best_of_n", "debate", "delphi"}
    assert {scheduler for _, scheduler in METHODS} >= {"fixed", "adaptive_voi"}


def test_suite_aggregate_reports_budget_matched_metrics() -> None:
    rows = [
        {
            "method": "single",
            "scheduler": "fixed",
            "success": True,
            "correctness": True,
            "speedup": 1.2,
            "cost_usd": 0.1,
            "tokens": 100,
            "latency_seconds": 2.0,
        },
        {
            "method": "single",
            "scheduler": "fixed",
            "success": False,
            "correctness": True,
            "speedup": 1.0,
            "cost_usd": 0.1,
            "tokens": 100,
            "latency_seconds": 2.0,
        },
    ]
    [summary] = _aggregate(rows)
    assert summary["tasks"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["correctness_rate"] == 1.0
    assert summary["median_speedup"] == 1.1
    assert summary["mean_cost_usd"] == 0.1
