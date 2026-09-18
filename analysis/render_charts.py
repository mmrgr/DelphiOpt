from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def render(source: Path, output: Path) -> None:
    rows = json.loads(source.read_text(encoding="utf-8"))
    keys = (
        "agent_mix",
        "mode",
        "scheduler",
        "status",
        "speedup",
        "cost_usd",
        "total_tokens",
        "latency_seconds",
        "llm_calls",
        "benchmark_runs",
        "rounds",
        "proposal_diversity",
    )
    table_rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key in keys) + "</tr>" for row in rows)

    def bars(metric: str, color: str) -> str:
        maximum = max((float(row.get(metric, 0)) for row in rows), default=1.0) or 1.0
        return "".join(
            f"<div class='bar' style='background:{color};width:{max(2, 420 * float(row.get(metric, 0)) / maximum):.1f}px'>{html.escape(str(row.get('agent_mix')))} / {html.escape(str(row.get('mode')))} / {html.escape(str(row.get('scheduler')))}: {float(row.get(metric, 0)):.3f}</div>"
            for row in rows
        )

    model_counts: dict[str, int] = {}
    expert_values: dict[str, list[float]] = {}
    for row in rows:
        for model, count in row.get("models_used", {}).items():
            model_counts[str(model)] = model_counts.get(str(model), 0) + int(count)
        for expert, value in row.get("expert_reliability", {}).items():
            expert_values.setdefault(str(expert), []).append(float(value))
    model_frequency = (
        "".join(f"<li>{html.escape(model)}: {count}</li>" for model, count in sorted(model_counts.items()))
        or "<li>No model calls recorded</li>"
    )
    expert_reputation = (
        "".join(
            f"<div class='bar' style='background:#6a7d2f;width:{max(2, 420 * sum(values) / len(values)):.1f}px'>{html.escape(expert)}: {sum(values) / len(values):.3f}</div>"
            for expert, values in sorted(expert_values.items())
        )
        or "No observations"
    )
    disagreement = "".join(
        f"<div><strong>{html.escape(str(row.get('agent_mix')))} / {html.escape(str(row.get('mode')))} / {html.escape(str(row.get('scheduler')))}</strong>: {', '.join(f'R{index + 1}={float(value):.3f}' for index, value in enumerate(row.get('round_disagreements', []))) or 'no rounds'}</div>"
        for row in rows
    )

    headings = "".join(f"<th>{html.escape(key)}</th>" for key in keys)
    document = f"""<!doctype html><meta charset='utf-8'><title>DelphiOpt ablation</title><style>body{{font:14px system-ui;margin:2rem}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.35rem}}.bar{{color:white;margin:.2rem 0;padding:.2rem;white-space:nowrap}}</style><h1>DelphiOpt ablation (simulation)</h1><h2>Cost vs speedup</h2>{bars("speedup", "#3478c9")}<h2>Tokens vs success</h2>{bars("total_tokens", "#6950a1")}<h2>Latency</h2>{bars("latency_seconds", "#a35d2d")}<h2>Proposal diversity</h2>{bars("proposal_diversity", "#2f8a62")}<h2>Rounds to convergence</h2>{bars("rounds", "#8b3f64")}<h2>Round-by-round disagreement</h2>{disagreement}<h2>Expert reputation</h2>{expert_reputation}<h2>Model selection frequency</h2><ul>{model_frequency}</ul><h2>Results</h2><table><tr>{headings}</tr>{table_rows}</table>"""
    output.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(Path(__file__).with_name("ablation_results.json")))
    parser.add_argument("--output", default=str(Path(__file__).with_name("ablation_report.html")))
    args = parser.parse_args()
    render(Path(args.input), Path(args.output))
    print(Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
