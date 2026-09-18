from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .sandbox import LocalSandbox


@dataclass(slots=True)
class ProfileFinding:
    file: str
    function: str
    loops: int
    membership_checks: int
    calls: int
    lines: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StaticProfiler:
    """Small deterministic profiler front-end; runtime evidence comes from BenchmarkEngine."""

    def analyze(self, project: str | Path) -> list[ProfileFinding]:
        root = Path(project)
        findings: list[ProfileFinding] = []
        for path in root.rglob("*.py"):
            if any(part in {".git", ".delphiopt", "__pycache__"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if not functions:
                functions = [tree]  # type: ignore[list-item]
            for function in functions:
                nodes = list(ast.walk(function))
                findings.append(
                    ProfileFinding(
                        str(path.relative_to(root)),
                        getattr(function, "name", "module"),
                        sum(isinstance(node, (ast.For, ast.While)) for node in nodes),
                        sum(isinstance(node, ast.Compare) and any(isinstance(op, ast.In) for op in node.ops) for node in nodes),
                        sum(isinstance(node, ast.Call) for node in nodes),
                        len(text.splitlines()),
                    )
                )
        return findings

    def context(self, project: str | Path) -> str:
        return "\n".join(str(finding.to_dict()) for finding in self.analyze(project))[:12000]


@dataclass(slots=True)
class DynamicProfile:
    command: str
    hotspots: list[str]
    categories: dict[str, int]
    return_code: int
    elapsed_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DynamicProfiler:
    """Run Python benchmark scripts under cProfile and classify observed hotspots."""

    def __init__(self, sandbox: LocalSandbox | None = None) -> None:
        self.sandbox = sandbox or LocalSandbox()

    def profile(self, command: str, project: str | Path, timeout_seconds: float = 120) -> DynamicProfile:
        parts = shlex.split(command, posix=os.name != "nt")
        if len(parts) < 2 or Path(parts[0]).name.lower() not in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
            return DynamicProfile(command, [], {}, -1, error="dynamic profiling requires a Python benchmark command")
        profile_parts = [parts[0], "-m", "cProfile", "-s", "cumulative", *parts[1:]]
        profile_command = subprocess.list2cmdline(profile_parts) if os.name == "nt" else shlex.join(profile_parts)
        result = self.sandbox.run(profile_command, project, timeout_seconds)
        if not result.ok:
            return DynamicProfile(
                profile_command,
                [],
                {},
                result.return_code,
                result.elapsed_seconds,
                (result.stderr or result.stdout)[-2000:],
            )
        hotspots = [line.strip() for line in result.stdout.splitlines() if _PROFILE_LINE.match(line)][:12]
        categories = {"cpu": 0, "memory": 0, "io": 0, "locks": 0}
        for hotspot in hotspots:
            lowered = hotspot.lower()
            if any(re.search(rf"\b{token}\b", lowered) for token in ("read", "write", "open", "socket", "pathlib")):
                categories["io"] += 1
            elif any(re.search(rf"\b{token}\b", lowered) for token in ("lock", "acquire", "thread", "semaphore")):
                categories["locks"] += 1
            elif any(re.search(rf"\b{token}\b", lowered) for token in ("alloc", "copy", "list", "dict", "set")):
                categories["memory"] += 1
            else:
                categories["cpu"] += 1
        return DynamicProfile(profile_command, hotspots, categories, result.return_code, result.elapsed_seconds)


_PROFILE_LINE = re.compile(r"^\s*\d+(?:/\d+)?\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+.+$")
