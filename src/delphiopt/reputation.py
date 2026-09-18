from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import Proposal


@dataclass(slots=True)
class Reputation:
    reliability: float = 0.5
    brier_sum: float = 0.0
    observations: int = 0
    prediction_error_sum: float = 0.0
    calibration_error_sum: float = 0.0

    @property
    def brier_score(self) -> float:
        return self.brier_sum / self.observations if self.observations else 0.25

    @property
    def calibration_error(self) -> float:
        return self.calibration_error_sum / self.observations if self.observations else 0.5

    @property
    def prediction_error(self) -> float:
        return self.prediction_error_sum / self.observations if self.observations else 0.0


class ExpertReputationManager:
    def __init__(self) -> None:
        self._items: dict[str, Reputation] = {}
        self._domains: dict[str, Reputation] = {}

    def get(self, expert_id: str) -> Reputation:
        return self._items.setdefault(expert_id, Reputation())

    def weight(self, expert_id: str, domain: str | None = None) -> float:
        item = self._domains.get(f"{expert_id}:{domain}") if domain else None
        return max(0.1, min(1.0, (item or self.get(expert_id)).reliability))

    def update(self, proposal: Proposal, *, correctness: bool, actual_speedup: float) -> None:
        outcome = 1.0 if correctness and actual_speedup >= 1.05 else 0.0
        self._update_item(self.get(proposal.source_expert), proposal, actual_speedup, outcome)
        domain_item = self._domains.setdefault(f"{proposal.source_expert}:{proposal.category}", Reputation())
        self._update_item(domain_item, proposal, actual_speedup, outcome)

    def _update_item(self, item: Reputation, proposal: Proposal, actual_speedup: float, outcome: float) -> None:
        item.observations += 1
        item.brier_sum += (proposal.confidence - outcome) ** 2
        item.calibration_error_sum += abs(proposal.confidence - outcome)
        item.prediction_error_sum += abs(proposal.expected_speedup - actual_speedup)
        item.reliability = 0.8 * item.reliability + 0.2 * (
            0.65 * outcome + 0.35 * (1 - min(1, abs(proposal.expected_speedup - actual_speedup)))
        )

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {
            key: {
                "reliability": value.reliability,
                "brier_score": value.brier_score,
                "calibration_error": value.calibration_error,
                "prediction_error": value.prediction_error,
                "observations": float(value.observations),
            }
            for key, value in self._items.items()
        }

    def full_snapshot(self) -> dict[str, dict[str, dict[str, float]]]:
        def serialize(items: dict[str, Reputation]) -> dict[str, dict[str, float]]:
            return {
                key: {
                    "reliability": value.reliability,
                    "brier_sum": value.brier_sum,
                    "observations": float(value.observations),
                    "prediction_error_sum": value.prediction_error_sum,
                    "calibration_error_sum": value.calibration_error_sum,
                }
                for key, value in items.items()
            }

        return {"experts": serialize(self._items), "domains": serialize(self._domains)}

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        os.close(fd)
        try:
            Path(temporary).write_text(json.dumps(self.full_snapshot(), indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @classmethod
    def load(cls, path: str | Path) -> ExpertReputationManager:
        manager = cls()
        source = Path(path)
        if not source.exists():
            return manager
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return manager
        for section, destination in (("experts", manager._items), ("domains", manager._domains)):
            for key, values in data.get(section, {}).items():
                destination[key] = Reputation(
                    reliability=float(values.get("reliability", 0.5)),
                    brier_sum=float(values.get("brier_sum", 0.0)),
                    observations=int(values.get("observations", 0)),
                    prediction_error_sum=float(values.get("prediction_error_sum", 0.0)),
                    calibration_error_sum=float(values.get("calibration_error_sum", 0.0)),
                )
        return manager
