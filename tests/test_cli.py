from __future__ import annotations

import json
import shutil
from pathlib import Path

from delphiopt.cli import _detect_project_commands, _effective_config, main


def test_cli_lists_builtin_modes(capsys) -> None:
    assert main(["models"]) == 0
    assert "mock" in capsys.readouterr().out
    assert main(["experts"]) == 0
    assert "algorithm" in capsys.readouterr().out


def test_cli_checks_model_capabilities(capsys) -> None:
    assert main(["models", "--check"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert any(values["reachable"] is True for values in result.values())


def test_cli_analysis_only_does_not_call_models(tmp_path: Path, capsys) -> None:
    (tmp_path / "target.py").write_text(
        "def f(values):\n    for value in values:\n        if value in values: return value\n", encoding="utf-8"
    )
    assert main(["optimize", str(tmp_path), "--only-analyze"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["findings"]


def test_explicit_config_preserves_project_commands(tmp_path: Path) -> None:
    (tmp_path / "delphiopt.yaml").write_text("project:\n  test_command: python tests.py\n", encoding="utf-8")
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("collaboration:\n  mode: single\n", encoding="utf-8")
    config = _effective_config(tmp_path, str(explicit))
    assert config["project"]["test_command"] == "python tests.py"
    assert config["collaboration"]["mode"] == "single"


def test_cli_detects_common_project_layout_and_benchmark_adapter(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires=[]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "benchmark_hot_loop.py").write_text("print('{}')\n", encoding="utf-8")
    commands = _detect_project_commands(tmp_path)
    assert commands == {"test_command": "pytest -q", "benchmark_command": "python benchmarks/benchmark_hot_loop.py"}


def test_cli_optimize_inspect_report_and_benchmark(tmp_path: Path, capsys) -> None:
    source = Path(__file__).parents[1] / "examples" / "demo_project"
    project = tmp_path / "demo"
    shutil.copytree(source, project)
    (project / "benchmark.py").write_text(
        "import json\nfrom pathlib import Path\ntext = Path('target.py').read_text()\nprint(json.dumps({'runtime_ms': 1.0 if 'wanted = set(wanted)' in text else 10.0}))\n",
        encoding="utf-8",
    )
    assert main(["optimize", str(project), "--mode", "single", "--max-rounds", "1"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "accepted"
    run_id = summary["run_id"]
    runs = project / ".delphiopt" / "runs"
    assert main(["inspect", run_id, "--runs-root", str(runs)]) == 0
    assert "run_finished" in capsys.readouterr().out
    assert main(["report", run_id, "--runs-root", str(runs)]) == 0
    assert (runs / f"{run_id}.html").exists()
    capsys.readouterr()
    assert main(["benchmark", str(project)]) == 0
    assert '"correctness": true' in capsys.readouterr().out.lower()


def test_cli_optimize_refuses_host_execution_when_disabled(tmp_path: Path, capsys) -> None:
    project = tmp_path / "locked"
    project.mkdir()
    (project / "tests.py").write_text("assert True\n", encoding="utf-8")
    (project / "benchmark.py").write_text("import json; print(json.dumps({'runtime_ms': 1.0}))\n", encoding="utf-8")
    (project / "delphiopt.yaml").write_text(
        "project:\n  test_command: python tests.py\n  benchmark_command: python benchmark.py\n"
        "sandbox:\n  allow_host_execution: false\n",
        encoding="utf-8",
    )
    assert main(["optimize", str(project)]) == 2
    assert "allow_host_execution" in capsys.readouterr().err


def test_cli_reproduce_replays_evidence_without_writing_source(tmp_path: Path, capsys) -> None:
    source = Path(__file__).parents[1] / "examples" / "demo_project"
    project = tmp_path / "demo"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".delphiopt", "__pycache__"))
    original = (project / "target.py").read_text(encoding="utf-8")

    assert main(["optimize", str(project)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert (project / "target.py").read_text(encoding="utf-8") != original

    # Revert the patch, then replay: reproduction must not touch the source again.
    (project / "target.py").write_text(original, encoding="utf-8")
    runs = project / ".delphiopt" / "runs"
    assert main(["reproduce", first["run_id"], "--runs-root", str(runs)]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["replay"] is True
    assert replay["status"] == "accepted_dry_run"
    assert (project / "target.py").read_text(encoding="utf-8") == original


def test_cli_resume_uses_checkpoint_metadata(tmp_path: Path, capsys) -> None:
    project = tmp_path / "resume-project"
    project.mkdir()
    (project / "target.py").write_text("def identity(value):\n    return value\n", encoding="utf-8")
    (project / "tests.py").write_text("from target import identity\nassert identity(3) == 3\n", encoding="utf-8")
    (project / "benchmark.py").write_text("import json\nprint(json.dumps({'runtime_ms': 1.0}))\n", encoding="utf-8")
    (project / "delphiopt.yaml").write_text(
        "project:\n  test_command: python tests.py\n  benchmark_command: python benchmark.py\n"
        "benchmark:\n  warmups: 0\n  repetitions: 1\n"
        "delphi:\n  max_rounds: 1\n  meaningful_speedup: 100.0\n",
        encoding="utf-8",
    )
    assert main(["optimize", str(project)]) == 0
    first = json.loads(capsys.readouterr().out)
    runs = project / ".delphiopt" / "runs"
    run_config = runs / f"{first['run_id']}.run_config.yaml"
    config = json.loads(run_config.read_text(encoding="utf-8"))
    config["delphi"]["max_rounds"] = 2
    run_config.write_text(json.dumps(config), encoding="utf-8")
    assert main(["resume", first["run_id"], "--runs-root", str(runs)]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["run_id"] == first["run_id"]
    assert resumed["rounds"] == 2
