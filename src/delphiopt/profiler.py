from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
                findings.append(ProfileFinding(str(path.relative_to(root)), getattr(function, "name", "module"), sum(isinstance(node, (ast.For, ast.While)) for node in nodes), sum(isinstance(node, ast.Compare) and any(isinstance(op, ast.In) for op in node.ops) for node in nodes), sum(isinstance(node, ast.Call) for node in nodes), len(text.splitlines())))
        return findings

    def context(self, project: str | Path) -> str:
        return "\n".join(str(finding.to_dict()) for finding in self.analyze(project))[:12000]
