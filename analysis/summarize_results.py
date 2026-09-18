from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("agent_mix", "unknown")), str(row.get("mode", "unknown")), str(row.get("scheduler", "unknown")))].append(row)
    summaries: list[dict[str, Any]] = []
    for (agent_mix, mode, scheduler), items in sorted(groups.items()):
        successes = [item for item in items if item.get("status") == "accepted"]
        speedups = [max(float(item.get("speedup", 1.0)), 1e-9) for item in items]
        total_cost = sum(float(item.get("cost_usd", 0.0)) for item in items)
        verified_gain = sum(max(0.0, value - 1.0) for value in speedups)
        model_counts: dict[str, int] = defaultdict(int)
        reliability: dict[str, list[float]] = defaultdict(list)
        for item in items:
            for model, count in item.get("models_used", {}).items():
                model_counts[str(model)] += int(count)
            for expert, value in item.get("expert_reliability", {}).items():
                reliability[str(expert)].append(float(value))
        summaries.append(
            {
                "simulation": all(bool(item.get("simulation")) for item in items),
                "agent_mix": agent_mix,
                "mode": mode,
                "scheduler": scheduler,
                "runs": len(items),
                "success_rate": len(successes) / len(items),
                "correctness_preservation_rate": sum(bool(item.get("correctness")) for item in items) / len(items),
                "median_speedup": statistics.median(speedups),
                "geometric_mean_speedup": math.exp(sum(math.log(value) for value in speedups) / len(speedups)),
                "total_cost_usd": total_cost,
                "total_tokens": sum(int(item.get("total_tokens", 0)) for item in items),
                "median_latency_seconds": statistics.median(float(item.get("latency_seconds", 0.0)) for item in items),
                "mean_llm_calls": statistics.mean(float(item.get("llm_calls", 0)) for item in items),
                "mean_benchmark_runs": statistics.mean(float(item.get("benchmark_runs", 0)) for item in items),
                "mean_rounds": statistics.mean(float(item.get("rounds", 0)) for item in items),
                "mean_proposal_diversity": statistics.mean(float(item.get("proposal_diversity", 0.0)) for item in items),
                "mean_disagreement": statistics.mean(
                    statistics.mean(item.get("round_disagreements", [0.0])) if item.get("round_disagreements") else 0.0 for item in items
                ),
                "calibration_error": statistics.mean(float(item.get("calibration_error", 0.0)) for item in items),
                "prediction_error": statistics.mean(float(item.get("prediction_error", 0.0)) for item in items),
                "model_selection_frequency": dict(sorted(model_counts.items())),
                "expert_reliability": {expert: statistics.mean(values) for expert, values in sorted(reliability.items())},
                "cost_per_success": total_cost / len(successes) if successes else None,
                "verified_speedup_per_dollar": verified_gain / total_cost if total_cost > 0 else None,
            }
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(Path(__file__).with_name("ablation_results.json")))
    parser.add_argument("--output", default=str(Path(__file__).with_name("ablation_summary.json")))
    args = parser.parse_args()
    rows = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.write_text(json.dumps(summarize(rows), indent=2), encoding="utf-8")
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
