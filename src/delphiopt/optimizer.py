from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .budget import BudgetExhausted, BudgetManager
from .models import Proposal
from .sandbox import CommandResult, LocalSandbox


@dataclass(slots=True)
class PatchResult:
    applied: bool
    files: list[str]
    diff: str
    explanation: str
    originals: dict[str, bytes] = field(default_factory=dict)


class ImplementationAgent:
    """Applies a small, auditable transformation in an isolated project copy."""

    def apply(self, project: str | Path, proposal: Proposal) -> PatchResult:
        root = Path(project)
        if proposal.patch.strip():
            return self._apply_patch(root, proposal)
        before: dict[str, str] = {}
        after: dict[str, str] = {}
        originals: dict[str, bytes] = {}
        for path in root.rglob("*.py"):
            if any(part in {".git", ".delphiopt", "__pycache__"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            before[str(path.relative_to(root))] = text
            changed = self._transform(text, proposal)
            if changed != text:
                originals[str(path.relative_to(root))] = path.read_bytes()
                path.write_text(changed, encoding="utf-8")
                after[str(path.relative_to(root))] = changed
        lines: list[str] = []
        for name, changed in after.items():
            lines.extend(
                difflib.unified_diff(before[name].splitlines(True), changed.splitlines(True), fromfile=f"a/{name}", tofile=f"b/{name}")
            )
        return PatchResult(bool(after), list(after), "".join(lines), self._explanation(proposal, after), originals)

    def _apply_patch(self, root: Path, proposal: Proposal) -> PatchResult:
        modified: dict[str, str] = {}
        originals: dict[str, bytes] = {}
        lines = proposal.patch.splitlines(keepends=True)
        index = 0
        while index < len(lines):
            if not lines[index].startswith("--- "):
                index += 1
                continue
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise ValueError("invalid unified diff file header")
            new_name = lines[index + 1][4:].strip().split("\t", 1)[0]
            relative = new_name.removeprefix("b/")
            target = (root / relative).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                raise ValueError(f"patch target is outside project or missing: {relative}")
            original = target.read_text(encoding="utf-8")
            if relative in modified:
                raise ValueError(f"duplicate patch target: {relative}")
            originals[relative] = target.read_bytes()
            source = original.splitlines(keepends=True)
            output: list[str] = []
            source_index = 0
            index += 2
            while index < len(lines) and not lines[index].startswith("--- "):
                if not lines[index].startswith("@@"):
                    index += 1
                    continue
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", lines[index])
                if not match:
                    raise ValueError("invalid unified diff hunk header")
                old_start = int(match.group(1)) - 1
                if old_start < source_index or old_start > len(source):
                    raise ValueError("unified diff hunk is out of range")
                output.extend(source[source_index:old_start])
                source_index = old_start
                index += 1
                while index < len(lines) and not lines[index].startswith(("@@", "--- ")):
                    line = lines[index]
                    if line.startswith("\\ No newline"):
                        index += 1
                        continue
                    prefix, content = line[:1], line[1:]
                    if prefix in {" ", "-"}:
                        if source_index >= len(source) or source[source_index].rstrip("\r\n") != content.rstrip("\r\n"):
                            raise ValueError("unified diff context does not match source")
                        if prefix == " ":
                            output.append(source[source_index])
                        source_index += 1
                    elif prefix == "+":
                        output.append(content)
                    else:
                        raise ValueError("invalid unified diff line")
                    index += 1
            output.extend(source[source_index:])
            modified[relative] = "".join(output)
        if not modified:
            return PatchResult(False, [], proposal.patch, "Unified diff did not contain a supported file change.")
        for relative, text in modified.items():
            (root / relative).write_text(text, encoding="utf-8")
        return PatchResult(True, list(modified), proposal.patch, self._explanation(proposal, modified), originals)

    def _transform(self, text: str, proposal: Proposal) -> str:
        key = proposal.transformation.lower()
        if "membership" in key and "def count_matches" in text and "wanted = set(wanted)" not in text:
            marker = "    count = 0\n"
            if marker in text:
                return text.replace(marker, "    wanted = set(wanted)\n" + marker, 1)
        return text

    def _explanation(self, proposal: Proposal, files: dict[str, str]) -> str:
        if files:
            return f"Applied {proposal.transformation} to {', '.join(files)}."
        return "No supported source pattern matched this proposal; candidate was retained for evidence only."

    def sync_accepted_files(
        self, source: str | Path, destination: str | Path, files: list[str], *, expected_originals: dict[str, bytes]
    ) -> None:
        source_root, destination_root = Path(source), Path(destination)
        backups: dict[Path, bytes | None] = {}
        # The user may edit the project while tests and benchmarks run. Refuse
        # to replace those edits with an older isolated-workspace snapshot.
        for relative in files:
            target = destination_root / relative
            if relative not in expected_originals or not target.is_file() or target.read_bytes() != expected_originals[relative]:
                raise ValueError(f"source changed during optimization: {relative}")
        try:
            for relative in files:
                target = destination_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                backups[target] = target.read_bytes() if target.exists() else None
                fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
                os.close(fd)
                shutil.copy2(source_root / relative, temporary)
                os.replace(temporary, target)
        except Exception:
            for target, content in backups.items():
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(content)
            raise


@dataclass(slots=True)
class GateResult:
    passed: bool
    test_result: CommandResult
    reason: str
    stages: list[CommandResult] = field(default_factory=list)


class CorrectnessGate:
    def __init__(self, sandbox: LocalSandbox | None = None) -> None:
        self.sandbox = sandbox or LocalSandbox()

    def run(
        self,
        project: str | Path,
        test_command: str,
        timeout_seconds: float = 120,
        *,
        lint_command: str | None = None,
        type_command: str | None = None,
        budget: BudgetManager | None = None,
    ) -> GateResult:
        stages: list[CommandResult] = []
        commands = [("compile", "python -m compileall -q .")]
        if lint_command:
            commands.append(("lint", lint_command))
        if type_command:
            commands.append(("type", type_command))
        commands.append(("tests", test_command))
        for name, command in commands:
            if budget:
                try:
                    budget.reserve_tool()
                except BudgetExhausted as exc:
                    result = CommandResult(command, -1, "", str(exc), 0.0)
                    return GateResult(False, result, f"{name} budget exhausted", stages + [result])
            result = self.sandbox.run(command, project, timeout_seconds)
            if budget:
                budget.record_elapsed(result.elapsed_seconds)
            stages.append(result)
            if not result.ok:
                return GateResult(False, result, f"{name} failed or timed out", stages)
        return GateResult(True, stages[-1], "tests passed", stages)
