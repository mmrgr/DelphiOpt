from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CommandResult:
    command: str
    return_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.return_code == 0 and not self.timed_out


class LocalSandbox:
    """Development fallback; use DockerSandbox for untrusted code."""

    def run(self, command: str, cwd: str | Path, timeout_seconds: float = 120) -> CommandResult:
        return self._execute(command, cwd, timeout_seconds, shell=True)

    def _execute(self, command: str | list[str], cwd: str | Path, timeout_seconds: float, *, shell: bool) -> CommandResult:
        started = time.perf_counter()
        display = command if isinstance(command, str) else subprocess.list2cmdline(command)
        try:
            completed = subprocess.run(command, cwd=str(cwd), shell=shell, capture_output=True, text=True, timeout=timeout_seconds, env=os.environ.copy(), check=False)
            return CommandResult(display, completed.returncode, completed.stdout, completed.stderr, time.perf_counter() - started)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CommandResult(display, -1, stdout, stderr, time.perf_counter() - started, True)
        except OSError as exc:
            return CommandResult(display, -1, "", str(exc), time.perf_counter() - started)


class DockerSandbox(LocalSandbox):
    def __init__(self, *, cpu_limit: int = 2, memory_mb: int = 2048, network: bool = False, image: str = "python:3.12-slim") -> None:
        self.cpu_limit, self.memory_mb, self.network, self.image = cpu_limit, memory_mb, network, image

    def run(self, command: str, cwd: str | Path, timeout_seconds: float = 120) -> CommandResult:
        args = ["docker", "run", "--rm"]
        if not self.network:
            args.extend(["--network", "none"])
        args.extend(["--cpus", str(self.cpu_limit), "--memory", f"{self.memory_mb}m", "-v", f"{Path(cwd).resolve()}:/workspace", "-w", "/workspace", self.image, "sh", "-lc", command])
        return self._execute(args, cwd, timeout_seconds, shell=False)


def sandbox_from_config(config: dict[str, Any] | None = None) -> LocalSandbox:
    values = config or {}
    kind = str(values.get("type", "local")).lower()
    if kind == "local":
        return LocalSandbox()
    if kind == "docker":
        return DockerSandbox(cpu_limit=int(values.get("cpu_limit", 2)), memory_mb=int(values.get("memory_mb", 2048)), network=bool(values.get("network", False)), image=str(values.get("image", "python:3.12-slim")))
    raise ValueError(f"unknown sandbox type: {kind}")
