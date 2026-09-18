from __future__ import annotations

import shutil
from pathlib import Path

from delphiopt.config import load_config
from delphiopt.runtime import OptimizationRuntime


def test_mock_end_to_end_accepts_verified_patch(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "examples" / "demo_project"
    project = tmp_path / "demo_project"
    shutil.copytree(source, project)
    summary = OptimizationRuntime().optimize(project)
    assert summary.status == "accepted"
    assert summary.correctness is True
    assert summary.speedup >= 1.05
    assert summary.winning_proposal
    assert len(summary.round_disagreements) == summary.rounds
    assert sum(summary.models_used.values()) == summary.llm_calls
    assert summary.expert_reliability
    assert 0 <= summary.calibration_error <= 1
    assert summary.prediction_error >= 0
    assert "wanted = set(wanted)" in (project / "target.py").read_text(encoding="utf-8")
    assert list((project / ".delphiopt" / "runs").glob(f"{summary.run_id}.jsonl"))


def test_failed_correctness_gate_never_runs_benchmark(tmp_path: Path) -> None:
    project = tmp_path / "broken"
    project.mkdir()
    (project / "tests.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    (project / "benchmark.py").write_text("from pathlib import Path\nPath('benchmark-ran').write_text('bad')\n", encoding="utf-8")
    (project / "delphiopt.yaml").write_text(
        "project:\n  test_command: python tests.py\n  benchmark_command: python benchmark.py\n", encoding="utf-8"
    )
    summary = OptimizationRuntime().optimize(project)
    assert summary.status == "baseline_failed"
    assert not (project / "benchmark-ran").exists()


def test_delphi_runs_controlled_feedback_round_when_no_patch_applies(tmp_path: Path) -> None:
    project = tmp_path / "generic"
    project.mkdir()
    (project / "target.py").write_text("def identity(value):\n    return value\n", encoding="utf-8")
    (project / "tests.py").write_text("from target import identity\nassert identity(3) == 3\n", encoding="utf-8")
    (project / "benchmark.py").write_text("import json\nprint(json.dumps({'runtime_ms': 1.0}))\n", encoding="utf-8")
    config = load_config()
    config["project"] = {"test_command": "python tests.py", "benchmark_command": "python benchmark.py"}
    config["benchmark"].update({"warmups": 0, "repetitions": 1})
    config["delphi"]["max_rounds"] = 2
    summary = OptimizationRuntime(config).optimize(project)
    assert summary.status == "rejected"
    assert summary.rounds == 2
    assert 0 < summary.llm_calls < 10
    assert len(summary.round_disagreements) == 2
