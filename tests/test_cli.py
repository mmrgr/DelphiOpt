from __future__ import annotations

import json
import shutil
from pathlib import Path

from delphiopt.cli import _effective_config, main


def test_cli_lists_builtin_modes(capsys) -> None:
    assert main(["models"]) == 0
    assert "mock" in capsys.readouterr().out
    assert main(["experts"]) == 0
    assert "algorithm" in capsys.readouterr().out


def test_explicit_config_preserves_project_commands(tmp_path: Path) -> None:
    (tmp_path / "delphiopt.yaml").write_text("project:\n  test_command: python tests.py\n", encoding="utf-8")
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("collaboration:\n  mode: single\n", encoding="utf-8")
    config = _effective_config(tmp_path, str(explicit))
    assert config["project"]["test_command"] == "python tests.py"
    assert config["collaboration"]["mode"] == "single"


def test_cli_optimize_inspect_report_and_benchmark(tmp_path: Path, capsys) -> None:
    source = Path(__file__).parents[1] / "examples" / "demo_project"
    project = tmp_path / "demo"
    shutil.copytree(source, project)
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
