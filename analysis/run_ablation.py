from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from delphiopt.config import load_config
from delphiopt.runtime import OptimizationRuntime


def run(source: Path, output: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for agent_mix in ("homogeneous", "heterogeneous"):
        for mode in ("single", "debate", "delphi"):
            for strategy in ("fixed", "difficulty", "adaptive_voi"):
                with tempfile.TemporaryDirectory(prefix="delphiopt-ablation-") as directory:
                    project = Path(directory) / "project"
                    shutil.copytree(source, project)
                    config = load_config(source / "delphiopt.yaml")
                    config["collaboration"]["mode"] = mode
                    config["scheduler"]["strategy"] = strategy
                    config["delphi"]["max_rounds"] = 2
                    if agent_mix == "homogeneous":
                        for settings in config["experts"].values():
                            settings["model_pool"] = ["strong"]
                    summary = OptimizationRuntime(config).optimize(project)
                    rows.append({"simulation": True, "agent_mix": agent_mix, "mode": mode, "scheduler": strategy, **summary.to_dict()})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Mock-provider ablations; results are labeled simulation by design.")
    parser.add_argument("--project", default=str(Path(__file__).parents[1] / "examples" / "demo_project"))
    parser.add_argument("--output", default=str(Path(__file__).with_name("ablation_results.json")))
    args = parser.parse_args()
    rows = run(Path(args.project).resolve(), Path(args.output).resolve())
    print(json.dumps({"simulation": True, "rows": len(rows), "output": str(Path(args.output).resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
