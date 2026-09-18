from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .benchmark import BenchmarkEngine
from .budget import BudgetManager
from .config import load_config, load_config_overrides, merge_config, validate_config
from .optimizer import CorrectnessGate
from .profiler import DynamicProfiler, StaticProfiler
from .reporting import render_run_report
from .runtime import OptimizationRuntime
from .sandbox import sandbox_from_config
from .telemetry import read_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delphiopt", description="Adaptive Delphi multi-agent code optimization runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    optimize = sub.add_parser("optimize", help="analyze, patch, test, benchmark, and decide")
    optimize.add_argument("project", nargs="?", default=".")
    optimize.add_argument("--config")
    optimize.add_argument("--budget-usd", type=float)
    optimize.add_argument("--max-rounds", type=int)
    optimize.add_argument("--mode", choices=("single", "debate", "delphi"))
    optimize.add_argument("--dry-run", action="store_true", help="verify a candidate without writing source files")
    optimize.add_argument("--only-analyze", action="store_true", help="profile the project without calling models")
    optimize.add_argument("--max-files", type=int, help="maximum number of files an accepted patch may change")
    benchmark = sub.add_parser("benchmark", help="run a project benchmark")
    benchmark.add_argument("project")
    benchmark.add_argument("--config")
    for name in ("inspect", "report", "reproduce"):
        item = sub.add_parser(name)
        item.add_argument("run_id")
        item.add_argument("--runs-root", default=None)
    for name in ("models", "experts"):
        item = sub.add_parser(name)
        item.add_argument("--config")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "models":
        config = load_config(args.config) if args.config else load_config()
        for name, values in config["models"].items():
            print(f"{name}\t{values.get('model', name)}\t{values.get('provider', 'mock')}")
        return 0
    if args.command == "experts":
        config = load_config(args.config) if args.config else load_config()
        for name, values in config["experts"].items():
            print(f"{name}\t{values.get('persona', name)}\t{','.join(values.get('model_pool', []))}")
        return 0
    if args.command == "optimize":
        project = Path(args.project).resolve()
        config = _effective_config(project, args.config)
        if args.only_analyze:
            findings = [item.to_dict() for item in StaticProfiler().analyze(project)]
            benchmark_command = str(config.get("project", {}).get("benchmark_command", ""))
            dynamic = DynamicProfiler(sandbox_from_config(config.get("sandbox"))).profile(
                benchmark_command, project, float(config.get("benchmark", {}).get("timeout_seconds", 120))
            )
            print(json.dumps({"project": str(project), "findings": findings, "dynamic_profile": dynamic.to_dict()}, indent=2))
            return 0
        if args.budget_usd is not None:
            config["budget"]["max_cost_usd"] = args.budget_usd
        if args.max_rounds is not None:
            config["delphi"]["max_rounds"] = args.max_rounds
        if args.mode is not None:
            config["collaboration"]["mode"] = args.mode
        validate_config(config)
        optimize_summary = OptimizationRuntime(config).optimize(project, write_changes=not args.dry_run, max_modified_files=args.max_files)
        print(json.dumps(optimize_summary.to_dict(), indent=2))
        return 0 if optimize_summary.status in {"accepted", "accepted_dry_run", "rejected"} else 1
    if args.command == "benchmark":
        project = Path(args.project).resolve()
        config = _effective_config(project, args.config)
        cfg = config.get("project", {})
        sandbox = sandbox_from_config(config.get("sandbox"))
        budget = BudgetManager()
        gate = CorrectnessGate(sandbox).run(
            project,
            str(cfg.get("test_command", "pytest -q")),
            float(config.get("benchmark", {}).get("timeout_seconds", 120)),
            lint_command=str(cfg["lint_command"]) if cfg.get("lint_command") else None,
            budget=budget,
        )
        result = BenchmarkEngine(
            **{
                key: value
                for key, value in config.get("benchmark", {}).items()
                if key in {"warmups", "repetitions", "timeout_seconds", "bootstrap_resamples", "cpu_affinity"}
            },
            seed=int(config.get("seed", 0)),
            sandbox=sandbox,
        ).run(str(cfg.get("benchmark_command", "python benchmark.py")), project, budget, gate.passed)
        print(
            json.dumps(
                {
                    "correctness": gate.passed,
                    "gate_reason": gate.reason,
                    "test_output": gate.test_result.stdout[-2000:],
                    "benchmark": result.to_dict(),
                    "budget": budget.snapshot(),
                },
                indent=2,
            )
        )
        return 0 if gate.passed and result.return_code == 0 else 1
    root = Path(args.runs_root) if args.runs_root else _find_run_root(Path.cwd(), args.run_id)
    events = read_events(root, args.run_id)
    if args.command == "inspect":
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
        return 0
    if args.command == "report":
        out = root / f"{args.run_id}.html"
        render_run_report(events, out)
        print(out.resolve())
        return 0
    if args.command == "reproduce":
        finished = next((event for event in reversed(events) if event.get("event") == "run_finished"), None)
        project_path_str = finished.get("summary", {}).get("project") if finished else None
        if not project_path_str:
            print("run has no project metadata", file=sys.stderr)
            return 1
        run_config = root / f"{args.run_id}.run_config.yaml"
        reproduce_config = load_config(run_config) if run_config.exists() else None
        print(json.dumps(OptimizationRuntime(reproduce_config).optimize(str(project_path_str)).to_dict(), indent=2))
        return 0
    return 1


def _find_run_root(cwd: Path, run_id: str) -> Path:
    direct = cwd / ".delphiopt" / "runs"
    if (direct / f"{run_id}.jsonl").exists():
        return direct
    matches = list(cwd.rglob(f"{run_id}.jsonl"))
    if matches:
        return matches[0].parent
    return direct


def _effective_config(project: Path, explicit: str | None) -> dict[str, Any]:
    project_config = project / "delphiopt.yaml"
    config = load_config(project_config if project_config.exists() else None)
    if not project_config.exists():
        config["project"].update(_detect_project_commands(project))
    if explicit:
        config = merge_config(config, load_config_overrides(explicit))
    validate_config(config)
    return config


def _detect_project_commands(project: Path) -> dict[str, str]:
    return {
        "test_command": "python tests.py" if project.joinpath("tests.py").exists() else "pytest -q",
        "benchmark_command": "python benchmark.py",
    }


if __name__ == "__main__":
    raise SystemExit(main())
