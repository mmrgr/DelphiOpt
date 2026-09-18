from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def render_run_report(events: list[dict[str, Any]], output: str | Path) -> Path:
    target = Path(output)
    finished = next((event for event in reversed(events) if event.get("event") == "run_finished"), {})
    summary = finished.get("summary", {})
    budget = finished.get("budget", {}).get("usage", {})
    cards = {
        "Status": summary.get("status", "unknown"),
        "Speedup": f"{float(summary.get('speedup', 0)):.3f}x",
        "Correctness": summary.get("correctness", False),
        "Rounds": summary.get("rounds", 0),
        "Cost": f"${float(summary.get('cost_usd', 0)):.6f}",
        "Tokens": summary.get("total_tokens", 0),
        "LLM calls": budget.get("llm_calls", summary.get("llm_calls", 0)),
        "Benchmark runs": budget.get("benchmark_runs", summary.get("benchmark_runs", 0)),
    }
    card_html = "".join(
        f"<article><strong>{escape(str(key))}</strong><span>{escape(str(value))}</span></article>" for key, value in cards.items()
    )
    rows: list[str] = []
    for event in events:
        payload = {key: value for key, value in event.items() if key not in {"event", "run_id", "timestamp"}}
        decision = event.get("decision")
        expert = event.get("expert", decision.get("expert_id", "") if isinstance(decision, dict) else "")
        rows.append(
            "<tr>"
            f"<td>{float(event.get('timestamp', 0)):.3f}</td>"
            f"<td>{escape(str(event.get('event', '')))}</td>"
            f"<td>{escape(str(event.get('round', '')))}</td>"
            f"<td>{escape(str(expert))}</td>"
            f"<td><pre>{escape(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))}</pre></td>"
            "</tr>"
        )
    document = f"""<!doctype html><html><head><meta charset="utf-8"><title>DelphiOpt run report</title><style>
body{{font:14px system-ui;margin:2rem;color:#18202a}}h1{{margin-bottom:1rem}}section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.75rem}}article{{border:1px solid #d9e0e8;border-radius:8px;padding:.75rem;background:#f7f9fb}}article strong,article span{{display:block}}article span{{font-size:1.25rem;margin-top:.25rem}}table{{border-collapse:collapse;width:100%;margin-top:1.5rem}}th,td{{border:1px solid #d9e0e8;padding:.45rem;vertical-align:top;text-align:left}}pre{{margin:0;max-height:18rem;overflow:auto;white-space:pre-wrap}}th{{background:#eef3f8}}
</style></head><body><h1>DelphiOpt run {escape(str(finished.get("run_id", "")))}</h1><section>{card_html}</section><table><thead><tr><th>Timestamp</th><th>Event</th><th>Round</th><th>Expert</th><th>Evidence</th></tr></thead><tbody>{"".join(rows)}</tbody></table></body></html>"""
    target.write_text(document, encoding="utf-8")
    return target
