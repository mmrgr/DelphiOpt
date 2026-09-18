from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class RunTracer:
    def __init__(self, root: str | Path = ".delphiopt/runs", run_id: str | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.jsonl_path = self.root / f"{self.run_id}.jsonl"
        self.sqlite_path = self.root / "traces.sqlite3"
        self._write({"event": "run_started", "run_id": self.run_id, "timestamp": time.time()})

    def _write(self, event: dict[str, Any]) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        connection = sqlite3.connect(self.sqlite_path)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS events (run_id TEXT, timestamp REAL, event TEXT, payload TEXT)")
            connection.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (self.run_id, time.time(), event.get("event", "unknown"), json.dumps(event, ensure_ascii=False)))
            connection.commit()
        finally:
            connection.close()

    def record(self, event: str, **payload: Any) -> None:
        self._write({"event": event, "run_id": self.run_id, "timestamp": time.time(), **payload})

    def close(self, **payload: Any) -> None:
        self.record("run_finished", **payload)


def read_events(root: str | Path, run_id: str) -> list[dict[str, Any]]:
    path = Path(root) / f"{run_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
