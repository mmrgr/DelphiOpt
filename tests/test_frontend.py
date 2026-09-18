from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from frontend.app_backend import FrontendBackend
from delphiopt.runtime import OptimizationRuntime


def test_frontend_exposes_catalog_and_configuration(tmp_path: Path) -> None:
    backend = FrontendBackend(tmp_path / "home")
    model_code, models = backend.run_cli(["models"])
    expert_code, experts = backend.run_cli(["experts"])
    base = tmp_path / "custom.yaml"
    base.write_text("budget:\n  max_cost_usd: 2.5\n", encoding="utf-8")
    override = backend.make_override("fixed", 4, base)
    values = yaml.safe_load(override.read_text(encoding="utf-8"))

    assert model_code == expert_code == 0
    assert "mock" in models
    assert "algorithm" in experts
    assert values["budget"]["max_cost_usd"] == 2.5
    assert values["scheduler"]["strategy"] == "fixed"
    assert values["delphi"]["max_rounds"] == 4


def test_frontend_discovers_run_summaries(tmp_path: Path) -> None:
    backend = FrontendBackend(tmp_path / "home")
    runs = tmp_path / "project" / ".delphiopt" / "runs"
    runs.mkdir(parents=True)
    (runs / "run-123.summary.json").write_text(json.dumps({"status": "accepted", "speedup": 1.4}), encoding="utf-8")

    discovered = backend.list_runs(tmp_path / "project")

    assert discovered[0]["_run_id"] == "run-123"
    assert discovered[0]["status"] == "accepted"


def test_frontend_validates_settings_and_runs_project_preflight(tmp_path: Path) -> None:
    backend = FrontendBackend(tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    (project / "benchmark.py").write_text("print('ok')\n", encoding="utf-8")
    settings = backend.load_settings()

    code, output = backend.preflight(project, settings)

    assert code == 0
    assert "项目预检" in output
    assert "6/6 项通过" in output
    assert backend.validate_settings({"budget": {"max_tokens": 0}}) == (False, "budget.max_tokens must be positive")


def test_frontend_preserves_raw_yaml_extensions(tmp_path: Path) -> None:
    backend = FrontendBackend(tmp_path / "home")
    path = tmp_path / "custom.yaml"
    values = {"models": {"local": {"provider": "mock", "model": "custom"}}, "ui": {"accent": "cyan"}}

    backend.save_settings(path, values)
    loaded = backend.load_settings(path)

    assert loaded["models"]["local"]["model"] == "custom"
    assert loaded["ui"]["accent"] == "cyan"


def test_frontend_tests_mock_model_and_runtime_priority_failover(tmp_path: Path) -> None:
    backend = FrontendBackend(tmp_path / "home")
    code, output = backend.test_model_connection({"provider": "mock", "model": "mock-custom"})
    runtime = OptimizationRuntime({
        "models": {
            "first": {"provider": "mock", "model": "one"},
            "second": {"provider": "mock", "model": "two"},
        },
        "experts": {"algorithm": {"persona": "test", "model_pool": ["first", "second"]}},
        "model_priority": ["second", "first"],
        "model_priority_enabled": True,
    })

    assert code == 0
    assert "连接成功" in output
    assert runtime._model_candidates("algorithm", "first") == ["second", "first"]


def test_frontend_tests_custom_openai_compatible_endpoint(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.update({"path": self.path, "model": body["model"], "authorization": self.headers["Authorization"]})
            payload = json.dumps({
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = FrontendBackend(tmp_path / "home")
        code, output = backend.test_model_connection({
            "provider": "openai-compatible",
            "model": "custom-model",
            "endpoint": f"http://127.0.0.1:{server.server_port}/custom/chat",
            "api_key_env": "CUSTOM_FRONTEND_TEST_KEY",
        }, "secret-key")
    finally:
        server.shutdown()
        server.server_close()

    assert code == 0
    assert "连接成功" in output
    assert received == {
        "path": "/custom/chat",
        "model": "custom-model",
        "authorization": "Bearer secret-key",
    }
