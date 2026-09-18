from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .agents import ExpertAgent
from .benchmark import BenchmarkEngine
from .budget import BudgetExhausted, BudgetManager
from .collaboration import CollaborationMode, visible_peer_feedback
from .config import load_config, merge_config, validate_config
from .delphi import CandidateWeights, ConvergencePolicy, DelphiProtocol, DelphiRound, StoppingPolicy
from .models import BudgetLimits, Proposal, RunSummary
from .optimizer import CorrectnessGate, ImplementationAgent
from .profiler import DynamicProfiler, StaticProfiler
from .providers import provider_from_config
from .reputation import ExpertReputationManager
from .sandbox import sandbox_from_config
from .scheduler import SchedulerState, make_scheduler
from .telemetry import RunTracer


class OptimizationRuntime:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = merge_config({}, config) if config is not None else None

    def optimize(self, project: str | Path, *, write_changes: bool = True, max_modified_files: int | None = None) -> RunSummary:
        project_path = Path(project).resolve()
        if not project_path.is_dir():
            raise FileNotFoundError(f"project directory does not exist: {project_path}")
        config_path = project_path / "delphiopt.yaml"
        if self.config is None:
            self.config = load_config(config_path if config_path.exists() else None)
        validate_config(self.config)
        run_id = uuid.uuid4().hex[:12]
        trace = RunTracer(project_path / ".delphiopt" / "runs", run_id)
        (project_path / ".delphiopt" / "runs" / f"{run_id}.run_config.yaml").write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        limits = BudgetLimits(
            **{key: value for key, value in self.config.get("budget", {}).items() if key in BudgetLimits.__dataclass_fields__}
        )
        budget = BudgetManager(limits)
        sandbox = sandbox_from_config(self.config.get("sandbox"))
        benchmark_cfg = self.config.get("benchmark", {})
        project_cfg = self.config.get("project", {})
        test_command = str(project_cfg.get("test_command", benchmark_cfg.get("test_command", "pytest -q")))
        lint_command = str(project_cfg["lint_command"]) if project_cfg.get("lint_command") else None
        benchmark_command = str(project_cfg.get("benchmark_command", benchmark_cfg.get("benchmark_command", "python benchmark.py")))
        timeout = float(benchmark_cfg.get("timeout_seconds", 120))
        engine = BenchmarkEngine(
            warmups=int(benchmark_cfg.get("warmups", 2)),
            repetitions=int(benchmark_cfg.get("repetitions", 7)),
            timeout_seconds=timeout,
            sandbox=sandbox,
            seed=int(self.config.get("seed", 0)),
            bootstrap_resamples=int(benchmark_cfg.get("bootstrap_resamples", 2000)),
            cpu_affinity=[int(item) for item in benchmark_cfg.get("cpu_affinity", [])],
        )
        trace.record(
            "config",
            config=self.config,
            python_version=__import__("sys").version,
            project=str(project_path),
            random_seed=self.config.get("seed", 0),
            git_commit=self._git_commit(project_path),
        )
        context = StaticProfiler().context(project_path)
        trace.record("static_analysis", context=context)
        baseline_gate = CorrectnessGate(sandbox).run(project_path, test_command, timeout, lint_command=lint_command, budget=budget)
        trace.record(
            "correctness",
            stage="baseline",
            passed=baseline_gate.passed,
            reason=baseline_gate.reason,
            stages=[
                {"command": item.command, "return_code": item.return_code, "timed_out": item.timed_out} for item in baseline_gate.stages
            ],
            return_code=baseline_gate.test_result.return_code,
            stdout=baseline_gate.test_result.stdout[-3000:],
            stderr=baseline_gate.test_result.stderr[-3000:],
        )
        if not baseline_gate.passed:
            summary = RunSummary(run_id, str(project_path), "baseline_failed", 0.0, 0.0, 1.0, False, 0, 0, stop_reason=baseline_gate.reason)
            return self._finish(trace, project_path, summary, budget)
        if bool(self.config.get("profiling", {}).get("dynamic", True)):
            try:
                budget.reserve_tool()
                dynamic_profile = DynamicProfiler(sandbox).profile(benchmark_command, project_path, timeout)
                budget.record_elapsed(dynamic_profile.elapsed_seconds)
                trace.record("dynamic_profile", result=dynamic_profile.to_dict())
                if dynamic_profile.hotspots:
                    context = f"{context}\nDynamic cProfile evidence:\n" + "\n".join(dynamic_profile.hotspots)
            except BudgetExhausted as exc:
                trace.record("dynamic_profile", skipped=True, reason=str(exc))
        baseline = engine.run(benchmark_command, project_path, budget, baseline_gate.passed)
        trace.record("benchmark", stage="baseline", result=baseline.to_dict())
        if not baseline.samples_ms:
            summary = RunSummary(
                run_id,
                str(project_path),
                "baseline_failed",
                baseline.median_ms,
                baseline.median_ms,
                1.0,
                False,
                0,
                0,
                stop_reason="baseline correctness or benchmark failed",
                cost_usd=budget.usage.cost_usd,
                total_tokens=budget.usage.total_tokens,
            )
            return self._finish(trace, project_path, summary, budget)

        reputation_path = project_path / ".delphiopt" / "reputation.json"
        reputation = ExpertReputationManager.load(reputation_path)
        scheduler_cfg = self.config.get("scheduler", {})
        scheduler = make_scheduler(
            str(scheduler_cfg.get("strategy", "adaptive_voi")),
            reputation=reputation,
            base_tokens=int(scheduler_cfg.get("base_tokens", 900)),
            tool_budget=int(scheduler_cfg.get("tool_budget", 2)),
            models=self.config.get("models", {}),
        )
        protocol_cfg = self.config.get("delphi", {})
        weights = CandidateWeights(
            **{
                key: float(value)
                for key, value in protocol_cfg.get("candidate_weights", {}).items()
                if key in CandidateWeights.__dataclass_fields__
            }
        )
        protocol = DelphiProtocol(
            reputation=reputation,
            max_rounds=int(protocol_cfg.get("max_rounds", 3)),
            disagreement_threshold=float(protocol_cfg.get("disagreement_threshold", 0.08)),
            minority_bonus=float(protocol_cfg.get("minority_bonus", 0.12)),
            weights=weights,
        )
        convergence = ConvergencePolicy(
            protocol.disagreement_threshold, protocol.max_rounds, int(protocol_cfg.get("no_improvement_rounds", 2))
        )
        stopping = StoppingPolicy(
            float(protocol_cfg.get("marginal_gain_threshold", 0.02)), float(protocol_cfg.get("min_utility_per_usd", 0.1))
        )
        experts = self._experts()
        mode = CollaborationMode(str(self.config.get("collaboration", {}).get("mode", "delphi")))
        if mode == CollaborationMode.SINGLE:
            experts = {key: value for key, value in experts.items() if key == "algorithm"}
        trace.record("collaboration_mode", mode=mode.value, expert_count=len(experts))
        implementer = ImplementationAgent()
        best_ms = baseline.median_ms
        winning = ""
        candidates_evaluated = 0
        proposal_diversity = 0.0
        round_disagreements: list[float] = []
        models_used: dict[str, int] = {}
        last_proposals: list[Proposal] = []
        previous_ranking: tuple[str, ...] = ()
        stagnant_rounds = 0
        stop_reason = "max rounds reached"
        completed: set[str] = set()
        evidence_log: list[str] = []
        model_stats: dict[str, dict[str, float]] = {}
        for round_number in range(1, protocol.max_rounds + 1):
            proposals: list[Proposal] = []
            observed_evidence = "\n".join(evidence_log[-12:]) or f"baseline median={baseline.median_ms:.3f} ms"
            feedback = protocol.feedback(last_proposals, observed_evidence) if round_number > 1 and last_proposals else ""
            completed.clear()
            while len(completed) < len(experts):
                current_evidence = proposals or last_proposals
                decision = scheduler.schedule(
                    SchedulerState(
                        list(experts),
                        difficulty=min(1.0, len(context) / 5000),
                        disagreement=protocol.disagreement(current_evidence) if current_evidence else 1.0,
                        candidate_gain=max(0.0, (current_evidence[0].expected_speedup - 1) if current_evidence else 1.0),
                        remaining_budget_ratio=budget.remaining_ratio(),
                        completed_experts=completed,
                        model_stats=model_stats,
                    )
                )
                expert_id = decision.expert_id
                if expert_id in completed or expert_id not in experts:
                    trace.record("scheduler_error", round=round_number, decision=decision.to_dict(), completed=sorted(completed))
                    break
                agent = experts[expert_id]
                model_candidates = self._model_candidates(expert_id, decision.model)
                decision.model = model_candidates[0]
                trace.record(
                    "scheduling_decision",
                    round=round_number,
                    decision=decision.to_dict(),
                    model_candidates=model_candidates,
                )
                if decision.action == "stop":
                    break
                completed.add(expert_id)
                if decision.action == "skip":
                    continue
                call_feedback = feedback
                if mode == CollaborationMode.DEBATE and proposals:
                    call_feedback = "Other agents' proposals are visible in this debate:\n" + visible_peer_feedback(proposals)
                proposal = None
                for model_alias in model_candidates:
                    model_cfg = self.config.get("models", {}).get(model_alias)
                    call_agent = agent
                    if model_cfg:
                        call_agent = ExpertAgent(
                            expert_id,
                            agent.persona,
                            str(model_cfg.get("model", model_alias)),
                            provider_from_config(model_cfg),
                        )
                    before_cost = budget.usage.cost_usd
                    before_latency = budget.usage.elapsed_seconds
                    before_calls = budget.usage.llm_calls
                    proposal = awaitable_run(call_agent, context, call_feedback, budget, trace, round_number, decision.max_tokens)
                    stats = model_stats.setdefault(model_alias, {"calls": 0.0, "successes": 0.0, "cost_usd": 0.0, "latency_seconds": 0.0})
                    stats["calls"] += budget.usage.llm_calls - before_calls
                    stats["cost_usd"] += budget.usage.cost_usd - before_cost
                    stats["latency_seconds"] += budget.usage.elapsed_seconds - before_latency
                    if proposal:
                        stats["successes"] += 1
                        decision.model = model_alias
                        models_used[model_alias] = models_used.get(model_alias, 0) + 1
                        break
                if proposal:
                    proposals.append(proposal)
            if not proposals:
                stop_reason = "no valid proposals or budget exhausted"
                break
            candidates = protocol.aggregate(proposals, round_number, trace)
            round_disagreement = protocol.disagreement(proposals)
            round_disagreements.append(round_disagreement)
            proposal_diversity = max(proposal_diversity, protocol.diversity(proposals))
            protocol.rounds.append(DelphiRound(round_number, proposals, candidates, round_disagreement))
            last_proposals = candidates
            should_stop, policy_reason = stopping.evaluate(
                expected_speedup=candidates[0].expected_speedup if candidates else 1.0,
                expected_cost_usd=max((candidate.implementation_cost for candidate in candidates), default=0.0),
                remaining_budget_ratio=budget.remaining_ratio(),
            )
            if should_stop:
                stop_reason = policy_reason
                break
            for candidate in candidates[: min(3, len(candidates))]:
                candidates_evaluated += 1
                workspace = Path(tempfile.mkdtemp(prefix=f"delphiopt-{run_id}-{candidate.id}-"))
                try:
                    shutil.copytree(
                        project_path,
                        workspace / "project",
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".delphiopt", "__pycache__"),
                    )
                    candidate_project = workspace / "project"
                    try:
                        budget.reserve_tool()
                    except BudgetExhausted:
                        stop_reason = "tool budget exhausted before implementation"
                        break
                    patch = implementer.apply(candidate_project, candidate)
                    trace.record(
                        "patch",
                        round=round_number,
                        proposal=candidate.to_dict(),
                        applied=patch.applied,
                        files=patch.files,
                        diff=patch.diff,
                        explanation=patch.explanation,
                    )
                    patch_dir = project_path / ".delphiopt" / "runs" / run_id / "patches"
                    patch_dir.mkdir(parents=True, exist_ok=True)
                    (patch_dir / f"{candidate.id}.diff").write_text(patch.diff, encoding="utf-8")
                    if not patch.applied:
                        reputation.update(candidate, correctness=False, actual_speedup=1.0)
                        evidence_log.append(f"candidate={candidate.id} patch=not-applied reason={patch.explanation}")
                        continue
                    file_limit = max_modified_files if max_modified_files is not None else int(project_cfg.get("max_modified_files", 3))
                    if len(patch.files) > file_limit:
                        reason = f"changed {len(patch.files)} files; limit is {file_limit}"
                        trace.record("candidate_decision", proposal_id=candidate.id, decision="rejected", reason=reason)
                        evidence_log.append(f"candidate={candidate.id} patch=rejected reason={reason}")
                        reputation.update(candidate, correctness=False, actual_speedup=1.0)
                        continue
                    gate = CorrectnessGate(sandbox).run(candidate_project, test_command, timeout, lint_command=lint_command, budget=budget)
                    trace.record(
                        "correctness",
                        stage="candidate",
                        round=round_number,
                        proposal_id=candidate.id,
                        passed=gate.passed,
                        reason=gate.reason,
                        stages=[
                            {"command": item.command, "return_code": item.return_code, "timed_out": item.timed_out} for item in gate.stages
                        ],
                        return_code=gate.test_result.return_code,
                        stdout=gate.test_result.stdout[-3000:],
                        stderr=gate.test_result.stderr[-3000:],
                    )
                    if not gate.passed:
                        reputation.update(candidate, correctness=False, actual_speedup=1.0)
                        evidence_log.append(f"candidate={candidate.id} correctness=failed reason={gate.reason}")
                        continue
                    comparison = engine.compare(benchmark_command, project_path, candidate_project, budget, True)
                    result = comparison.candidate
                    speedup = comparison.speedup
                    conservative_speedup = comparison.ci95_low
                    coefficient_of_variation = (
                        result.stddev_ms / result.mean_ms if result.mean_ms and result.mean_ms != float("inf") else float("inf")
                    )
                    trace.record(
                        "benchmark_comparison",
                        stage="candidate",
                        round=round_number,
                        proposal_id=candidate.id,
                        comparison=comparison.to_dict(),
                        coefficient_of_variation=coefficient_of_variation,
                    )
                    reputation.update(candidate, correctness=True, actual_speedup=speedup)
                    meaningful_speedup = float(protocol_cfg.get("meaningful_speedup", 1.05))
                    max_cv = float(protocol_cfg.get("max_coefficient_of_variation", 0.15))
                    evidence_log.append(
                        f"candidate={candidate.id} correctness=passed speedup={speedup:.4f} "
                        f"ci95=[{comparison.ci95_low:.4f},{comparison.ci95_high:.4f}] cv={coefficient_of_variation:.4f}"
                    )
                    file_limit = max_modified_files if max_modified_files is not None else int(project_cfg.get("max_modified_files", 3))
                    if len(patch.files) > file_limit:
                        reason = f"changed {len(patch.files)} files; limit is {file_limit}"
                        trace.record("candidate_decision", proposal_id=candidate.id, decision="rejected", reason=reason)
                        evidence_log.append(f"candidate={candidate.id} patch=rejected reason={reason}")
                        reputation.update(candidate, correctness=False, actual_speedup=1.0)
                        continue
                    if (
                        result.samples_ms
                        and speedup >= meaningful_speedup
                        and conservative_speedup >= meaningful_speedup
                        and coefficient_of_variation <= max_cv
                    ):
                        if write_changes:
                            implementer.sync_accepted_files(candidate_project, project_path, patch.files)
                        best_ms, winning = result.median_ms, candidate.id
                        status = "accepted" if write_changes else "accepted_dry_run"
                        stop_reason = (
                            "verified improvement accepted" if write_changes else "verified improvement; dry-run left source unchanged"
                        )
                        trace.record(
                            "candidate_decision",
                            proposal_id=candidate.id,
                            decision=status,
                            speedup=speedup,
                            reputation=reputation.snapshot(),
                        )
                        summary = RunSummary(
                            run_id,
                            str(project_path),
                            status,
                            comparison.baseline.median_ms,
                            best_ms,
                            speedup,
                            True,
                            round_number,
                            candidates_evaluated,
                            winning,
                            stop_reason,
                            budget.usage.cost_usd,
                            budget.usage.total_tokens,
                            proposal_diversity,
                        )
                        self._attach_experiment_metrics(summary, reputation, round_disagreements, models_used)
                        trace.record("reputation_update", values=reputation.snapshot())
                        reputation.save(reputation_path)
                        return self._finish(trace, project_path, summary, budget)
                    trace.record(
                        "candidate_decision",
                        proposal_id=candidate.id,
                        decision="rejected",
                        speedup=speedup,
                        reputation=reputation.snapshot(),
                    )
                finally:
                    shutil.rmtree(workspace, ignore_errors=True)
            ranking = tuple(candidate.normalized_key() for candidate in candidates)
            stagnant_rounds = stagnant_rounds + 1 if ranking == previous_ranking else 0
            should_stop, policy_reason = convergence.evaluate(
                round_number=round_number,
                disagreement=round_disagreement,
                ranking=ranking,
                previous_ranking=previous_ranking,
                stagnant_rounds=stagnant_rounds,
                remaining_budget_ratio=budget.remaining_ratio(),
            )
            if should_stop:
                stop_reason = policy_reason
                break
            previous_ranking = ranking
        summary = RunSummary(
            run_id,
            str(project_path),
            "rejected",
            baseline.median_ms,
            best_ms,
            baseline.median_ms / best_ms if best_ms else 1.0,
            True,
            len(protocol.rounds),
            candidates_evaluated,
            winning,
            stop_reason,
            budget.usage.cost_usd,
            budget.usage.total_tokens,
            proposal_diversity,
        )
        self._attach_experiment_metrics(summary, reputation, round_disagreements, models_used)
        reputation.save(reputation_path)
        return self._finish(trace, project_path, summary, budget)

    def _finish(self, trace: RunTracer, project: Path, summary: RunSummary, budget: BudgetManager) -> RunSummary:
        summary.cost_usd = budget.usage.cost_usd
        summary.total_tokens = budget.usage.total_tokens
        summary.latency_seconds = budget.usage.elapsed_seconds
        summary.llm_calls = budget.usage.llm_calls
        summary.benchmark_runs = budget.usage.benchmark_runs
        summary.tool_calls = budget.usage.tool_calls
        summary.verified_speedup_per_dollar = (summary.speedup - 1) / summary.cost_usd if summary.cost_usd > 0 else 0.0
        trace.close(summary=summary.to_dict(), budget=budget.snapshot())
        (project / ".delphiopt" / "runs" / f"{summary.run_id}.summary.json").write_text(
            json.dumps(summary.to_dict(), indent=2), encoding="utf-8"
        )
        return summary

    def _attach_experiment_metrics(
        self, summary: RunSummary, reputation: ExpertReputationManager, disagreements: list[float], models_used: dict[str, int]
    ) -> None:
        snapshot = reputation.snapshot()
        observed = [values for values in snapshot.values() if values["observations"] > 0]
        summary.round_disagreements = list(disagreements)
        summary.models_used = dict(sorted(models_used.items()))
        summary.expert_reliability = {key: values["reliability"] for key, values in sorted(snapshot.items())}
        summary.calibration_error = sum(values["calibration_error"] for values in observed) / len(observed) if observed else 0.0
        summary.prediction_error = sum(values["prediction_error"] for values in observed) / len(observed) if observed else 0.0

    def _experts(self) -> dict[str, ExpertAgent]:
        if self.config is None:
            raise RuntimeError("runtime configuration was not initialized")
        result: dict[str, ExpertAgent] = {}
        models = self.config.get("models", {})
        for expert_id, settings in self.config.get("experts", {}).items():
            pool = settings.get("model_pool", ["cheap"])
            model_name = str(pool[0])
            model_cfg = dict(models.get(model_name, {"provider": "mock", "model": model_name}))
            result[expert_id] = ExpertAgent(
                expert_id, str(settings.get("persona", expert_id)), str(model_cfg.get("model", model_name)), provider_from_config(model_cfg)
            )
        return result

    def _git_commit(self, project: Path) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else "unavailable"

    def _resolve_model_alias(self, expert_id: str, requested: str) -> str:
        return self._model_candidates(expert_id, requested)[0]

    def _model_candidates(self, expert_id: str, requested: str) -> list[str]:
        if self.config is None:
            raise RuntimeError("runtime configuration was not initialized")
        models = self.config.get("models", {})
        pool = [str(item) for item in self.config["experts"][expert_id].get("model_pool", []) if item in models]
        priority = [str(item) for item in self.config.get("model_priority", []) if item in models]
        if requested in models:
            preferred = [requested]
        elif pool:
            preferred = [pool[-1] if requested == "strong" else pool[0]]
        else:
            preferred = []
        ordered = priority + preferred + pool if self.config.get("model_priority_enabled", False) else preferred + pool + priority
        result: list[str] = []
        for alias in ordered or list(models):
            if alias in models and alias not in result:
                result.append(alias)
        if not result:
            raise ValueError(f"expert {expert_id} has no configured model")
        return result


def awaitable_run(
    agent: ExpertAgent, context: str, feedback: str, budget: BudgetManager, trace: RunTracer, round_number: int, max_tokens: int
) -> Proposal | None:
    import asyncio

    coroutine = (
        agent.revise(context, feedback, budget, trace, round_number, max_tokens)
        if feedback
        else agent.analyze(context, budget, trace, round_number, max_tokens=max_tokens)
    )
    return asyncio.run(coroutine)
