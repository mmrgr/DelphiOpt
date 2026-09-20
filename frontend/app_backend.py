from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


ROOT = bundle_root()
SOURCE = ROOT / "src"
if SOURCE.exists() and str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.render_charts import render  # noqa: E402
from analysis.run_ablation import run as run_ablation  # noqa: E402
from analysis.summarize_results import summarize  # noqa: E402
from delphiopt.cli import main as cli_main  # noqa: E402
from delphiopt.config import DEFAULT_CONFIG, load_config, merge_config, validate_config  # noqa: E402
from delphiopt.providers import provider_from_config  # noqa: E402


class FrontendBackend:
    """Thin adapter that keeps every desktop action on the real CLI/runtime."""

    def __init__(self, app_home: Path | None = None) -> None:
        self.app_home = app_home or Path.home() / "DelphiOpt"
        self.app_home.mkdir(parents=True, exist_ok=True)

    def ensure_demo(self) -> Path:
        destination = self.app_home / "demo_project"
        source = ROOT / "examples" / "demo_project"
        if not destination.exists():
            shutil.copytree(source, destination)
        return destination

    def run_cli(self, args: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                code = cli_main(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
        except Exception as exc:  # desktop boundary: surface backend failures in console
            code = 1
            stream.write(f"{type(exc).__name__}: {exc}\n")
        return code, stream.getvalue().strip()

    def make_override(
        self,
        scheduler: str,
        max_rounds: int,
        base: Path | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> Path:
        # A fixed shared path let two desktop instances (or two queued runs) overwrite
        # each other's overrides; every call now writes its own file.
        handle = tempfile.NamedTemporaryFile(prefix="delphiopt-desktop-", suffix=".yaml", delete=False, mode="w", encoding="utf-8")
        handle.close()
        path = Path(handle.name)
        values: dict[str, Any] = {}
        if base and base.exists():
            values = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        if overrides:
            values = merge_config(values, overrides)
        values.setdefault("scheduler", {})["strategy"] = scheduler
        values.setdefault("delphi", {})["max_rounds"] = max_rounds
        validate_config(merge_config(DEFAULT_CONFIG, values))
        path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        return path

    def load_settings(self, path: Path | None = None) -> dict[str, Any]:
        return load_config(path) if path else load_config()

    def save_settings(self, path: Path, values: dict[str, Any]) -> None:
        complete = merge_config(DEFAULT_CONFIG, values)
        validate_config(complete)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(values, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def validate_settings(self, values: dict[str, Any]) -> tuple[bool, str]:
        try:
            validate_config(merge_config(DEFAULT_CONFIG, values))
        except (TypeError, ValueError) as exc:
            return False, str(exc)
        return True, "配置有效"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "python": sys.version.split()[0],
            "app_home": str(self.app_home),
            "bundle_root": str(ROOT),
            "providers": {
                "模拟服务商": True,
                "OpenAI": bool(os.getenv("OPENAI_API_KEY")),
                "Anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
                "Gemini": bool(os.getenv("GEMINI_API_KEY")),
                "OpenAI 兼容接口": bool(os.getenv("OPENAI_COMPATIBLE_API_KEY")),
            },
        }

    @staticmethod
    def set_session_api_key(environment_name: str, api_key: str) -> None:
        name = environment_name.strip()
        if not name:
            raise ValueError("API 密钥环境变量名不能为空")
        if api_key:
            os.environ[name] = api_key

    def test_model_connection(self, settings: dict[str, Any], api_key: str = "") -> tuple[int, str]:
        try:
            provider_name = str(settings.get("provider", "mock"))
            model = str(settings.get("model", "")).strip()
            if not model:
                raise ValueError("模型名称不能为空")
            environment_name = str(settings.get("api_key_env", "")).strip()
            if provider_name != "mock":
                self.set_session_api_key(environment_name, api_key)
            provider = provider_from_config(settings)
            response = asyncio.run(
                provider.generate(
                    '仅返回一个 JSON 对象：{"status":"ok"}', model=model, max_tokens=32, temperature=0.0
                )
            )
            preview = response.text.replace("\n", " ")[:160]
            return 0, f"连接成功\n服务商：{provider.name}\n模型：{response.model}\n延迟：{response.latency_seconds:.2f} 秒\n响应：{preview}"
        except Exception as exc:
            return 1, f"连接失败：{type(exc).__name__}: {exc}"

    def preflight(self, project: Path, settings: dict[str, Any]) -> tuple[int, str]:
        checks = {
            "项目目录存在": project.is_dir(),
            "包含 Python 源文件": any(project.rglob("*.py")) if project.is_dir() else False,
            "测试命令已配置": bool(settings.get("project", {}).get("test_command")),
            "基准命令已配置": bool(settings.get("project", {}).get("benchmark_command")),
            "预算配置有效": self.validate_settings(settings)[0],
        }
        runs = project / ".delphiopt" / "runs"
        try:
            runs.mkdir(parents=True, exist_ok=True)
            checks["运行目录可写"] = True
        except OSError:
            checks["运行目录可写"] = False
        output = "\n".join(f"{'通过' if passed else '失败'}  {name}" for name, passed in checks.items())
        failed = sum(not value for value in checks.values())
        return (1 if failed else 0), f"项目预检\n{output}\n\n结果：{len(checks) - failed}/{len(checks)} 项通过"

    def list_runs(self, project: Path) -> list[dict[str, Any]]:
        root = project / ".delphiopt" / "runs"
        rows: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.summary.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                value["_run_id"] = path.name.removesuffix(".summary.json")
                value["_runs_root"] = str(root)
                rows.append(value)
            except (OSError, ValueError):
                continue
        return rows

    def execute_ablation(self, project: Path, notify: Callable[[str], None] | None = None) -> tuple[int, str]:
        output_dir = self.app_home / "experiments"
        output_dir.mkdir(parents=True, exist_ok=True)
        results = output_dir / "ablation_results.json"
        summary = output_dir / "ablation_summary.json"
        report = output_dir / "ablation_report.html"
        try:
            if notify:
                notify("正在运行 18 个真实模拟实验单元…")
            rows = run_ablation(project, results)
            summary.write_text(json.dumps(summarize(rows), indent=2), encoding="utf-8")
            render(results, report)
            return 0, f"已完成 {len(rows)} 个实验单元。\n结果：{results}\n汇总：{summary}\n报告：{report}"
        except Exception as exc:
            return 1, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def open_path(path: Path) -> None:
        os.startfile(path)  # type: ignore[attr-defined]
