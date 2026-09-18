from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
from pathlib import Path
from typing import Any

from delphiopt.config import load_config
from delphiopt.runtime import OptimizationRuntime

METHODS: tuple[tuple[str, str], ...] = (
    ("single", "fixed"),
    ("best_of_n", "fixed"),
    ("debate", "fixed"),
    ("delphi", "fixed"),
    ("delphi", "difficulty"),
    ("delphi", "adaptive_voi"),
)

MATCHED_BUDGET = {"max_cost_usd": 0.25, "max_tokens": 20_000, "max_llm_calls": 12, "max_benchmark_runs": 40}


def task_projects(root: Path, limit: int | None) -> list[Path]:
    projects = sorted(path for path in root.iterdir() if path.is_dir() and (path / "metadata.json").exists())
    return projects[:limit] if limit else projects


def run_suite(tasks_root: Path, output: Path, *, limit: int | None = None, config_path: Path | None = None) -> dict[str, Any]:
    base_config = load_config(config_path)
    rows: list[dict[str, Any]] = []
    for task in task_projects(tasks_root, limit):
        metadata = json.loads((task / "metadata.json").read_text(encoding="utf-8"))
        for mode, strategy in METHODS:
            with tempfile.TemporaryDirectory(prefix=f"delphiopt-suite-{task.name}-") as directory:
                project = Path(directory) / task.name
                shutil.copytree(task, project)
                config = json.loads(json.dumps(base_config))
                config["project"] = {
                    "test_command": metadata["test_command"],
                    "benchmark_command": metadata["benchmark_command"],
                    "max_modified_files": 1,
                }
                config["collaboration"] = {"mode": mode, "best_of_n": 3}
                config["scheduler"]["strategy"] = strategy
                config["delphi"]["max_rounds"] = 2
                config["budget"].update(MATCHED_BUDGET)
                summary = OptimizationRuntime(config).optimize(project, write_changes=False)
                providers = {str(values.get("provider", "mock")) for values in config["models"].values()}
                provider_mode = "mock" if providers == {"mock"} else "real" if "mock" not in providers else "mixed"
                rows.append(
                    {
                        "task": metadata["id"],
                        "category": metadata["category"],
                        "method": mode,
                        "scheduler": strategy,
                        "provider_mode": provider_mode,
                        "simulation": provider_mode == "mock",
                        "status": summary.status,
                        "success": summary.status in {"accepted", "accepted_dry_run"},
                        "correctness": summary.correctness,
                        "speedup": summary.speedup,
                        "cost_usd": summary.cost_usd,
                        "tokens": summary.total_tokens,
                        "latency_seconds": summary.latency_seconds,
                        "llm_calls": summary.llm_calls,
                        "benchmark_runs": summary.benchmark_runs,
                        "rounds": summary.rounds,
                    }
                )
    aggregate = _aggregate(rows)
    modes = {str(row["provider_mode"]) for row in rows}
    result = {
        "provider_mode": modes.pop() if len(modes) == 1 else "mixed",
        "simulation": bool(rows) and all(row["simulation"] for row in rows),
        "matched_budget": MATCHED_BUDGET,
        "rows": rows,
        "aggregate": aggregate,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["method"]), str(row["scheduler"])), []).append(row)
    result: list[dict[str, Any]] = []
    for (method, scheduler), values in sorted(grouped.items()):
        result.append(
            {
                "method": method,
                "scheduler": scheduler,
                "tasks": len(values),
                "success_rate": sum(bool(item["success"]) for item in values) / len(values),
                "correctness_rate": sum(bool(item["correctness"]) for item in values) / len(values),
                "median_speedup": statistics.median(float(item["speedup"]) for item in values),
                "mean_cost_usd": sum(float(item["cost_usd"]) for item in values) / len(values),
                "mean_tokens": sum(int(item["tokens"]) for item in values) / len(values),
                "mean_latency_seconds": sum(float(item["latency_seconds"]) for item in values) / len(values),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a budget-matched DelphiOpt benchmark suite.")
    parser.add_argument("--tasks-root", default=str(Path(__file__).parents[1] / "benchmarks" / "tasks"))
    parser.add_argument("--output", default=str(Path(__file__).with_name("suite_results.json")))
    parser.add_argument("--limit", type=int, default=None, help="limit task count for a smoke run")
    parser.add_argument("--config", default=None, help="use real provider configuration instead of the Mock Provider")
    args = parser.parse_args()
    result = run_suite(Path(args.tasks_root).resolve(), Path(args.output).resolve(), limit=args.limit, config_path=args.config)
    print(
        json.dumps({"simulation": result["simulation"], "rows": len(result["rows"]), "output": str(Path(args.output).resolve())}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
