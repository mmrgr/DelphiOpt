# DelphiOpt V1 functional audit

Audit date: 2026-09-17

## Coverage matrix

| Area | Verified behavior | Evidence |
|---|---|---|
| Configuration | Deep, non-aliasing merge; precedence defaults → project → explicit config → CLI; positive budgets; valid modes/strategies; valid expert model pools | `tests/test_core.py`, `tests/test_cli.py` |
| Providers | Mock, OpenAI/OpenAI-compatible, Anthropic, Gemini request/response adapters; provider token usage; API-key errors; structured-output repair | `providers.py`, provider-shape tests, `configs/real-providers.yaml.example` |
| Expert agents | Five configurable personas; independent first-round prompts; schema-validated proposals; anonymous IDs; allocated `max_tokens` reaches the provider | agent tests and `agent_call` trace records |
| Delphi | Deduplication, configurable weighted ranking, minority preservation, anonymous controlled feedback, disagreement and diversity metrics | Delphi unit tests and aggregation traces |
| Collaboration | `single`, `debate`, and `delphi` share the same implementation/test/benchmark path | CLI and 18-cell ablation |
| Scheduling | `fixed`, `difficulty`, and `adaptive_voi`; scheduler-selected expert and resolved model alias are actually invoked; completed experts are excluded | scheduler tests and scheduling traces |
| Stopping | Marginal utility, remaining budget, maximum rounds, stable ranking, disagreement, and stagnant-round policies | stopping/convergence tests |
| Budget | Actual LLM cost/tokens/latency plus compile, lint, tests, warmups, repetitions, implementation tools, and benchmark runs | budget tests and run summary fields |
| Reputation | Persistent overall and expert/domain reliability, Brier score, calibration error, prediction error, correctness, and observed speedup | reputation persistence tests and `.delphiopt/reputation.json` |
| Patching | Deterministic demo transform and validated in-project unified diffs; isolated candidate copies; atomic accepted-file replacement with restoration on failure | patch tests and persisted `.diff` files |
| Correctness | Compile → optional lint → tests; failed baseline or candidate correctness prevents performance ranking | gate tests and failed-baseline integration test |
| Benchmarking | Warmups and repetitions count against budget; runtime, throughput, memory, mean, median, standard deviation, and 95% interval | benchmark tests and CLI output |
| Acceptance | Median speedup, conservative CI speedup, maximum coefficient of variation, and correctness must pass | runtime integration and candidate trace |
| Sandboxes | Config-selected Local or Docker execution; Docker uses argv execution, disabled network option, CPU/memory limits, timeout, and mounted isolated workspace | sandbox factory tests and `docs/safety.md` |
| Observability | JSONL and SQLite events, run configuration, git revision, seed, decisions, evidence, patches, budgets, reputation, summary, and rich HTML report | trace/report CLI integration test |
| CLI | `optimize`, `benchmark`, `inspect`, `report`, `reproduce`, `models`, and `experts` | CLI tests |
| Dataset | Ten distinct executable tasks covering algorithm, loops, data structures, strings, numerical work, memory, I/O, serialization, concurrency, and caching | `benchmarks/generate_tasks.py`; all task tests and benchmarks pass |
| Ablation | Homogeneous/heterogeneous × single/debate/Delphi × fixed/difficulty/adaptive VOI | 18 simulation rows in `analysis/ablation_results.json` |
| Metrics/reporting | Success, correctness, median/geometric speedup, cost, tokens, latency, calls, benchmark runs, rounds, diversity, disagreement, calibration, prediction error, model frequency, expert reliability, cost/success, speedup/dollar | `analysis/summarize_results.py`, `analysis/render_charts.py` |
| Packaging/CI | Editable install, wheel build, Ruff, mypy, pytest, coverage threshold | `pyproject.toml`, `.github/workflows/ci.yml` |

## Defects corrected during audit

1. Project configuration previously replaced explicit CLI state; the CLI now performs deterministic layered merging.
2. Mutable default configuration previously leaked changes between runs; merges now deep-copy all values.
3. Scheduler decisions previously selected one expert while the runtime called another; scheduler order now drives invocation directly.
4. Difficulty routing previously reselected completed experts; every policy now filters the completed set.
5. Scheduled token allocations previously stopped at the trace; `max_tokens` now reaches provider calls.
6. Warmups and host commands previously escaped global tool/benchmark/latency accounting; all executions now consume shared budget.
7. A failed baseline test previously still ran the benchmark; correctness failure now terminates before performance execution.
8. Candidate convergence previously used deduplicated candidates and could stop after one failed round; it now evaluates raw disagreement and stable rankings across rounds.
9. Runtime always used LocalSandbox; sandbox selection now follows validated configuration.
10. Reputation previously reset every run and lacked domain history; it is now persisted atomically with overall and domain records.
11. Real-model malformed output and response-shape errors could terminate the run; provider errors are normalized and proposal repair is retried once.
12. The implementation path previously recognized one demo pattern only; it now also validates and applies safe in-project unified diffs.
13. Acceptance previously used a permissive absolute variance gate; it now requires median gain, conservative CI gain, and bounded coefficient of variation.
14. The HTML report previously listed event names only; it now renders metrics, budget use, experts, decisions, and full evidence payloads.
15. The benchmark dataset previously repeated one fixture under ten labels; every category now has distinct code, tests, workload, metadata, and opportunity.
16. Dataset regeneration previously produced three Ruff-invalid import blocks; generator templates now preserve module-level spacing.
17. Experiment output previously omitted model frequency, expert reliability, calibration, prediction error, and round disagreement; summaries and HTML charts now expose all five.
18. Reputation previously reported speedup prediction error under the calibration-error label; confidence calibration and speedup prediction error now have separate persisted metrics.

## Verified limits

* Mock-provider ablations are simulation data and carry `simulation: true` in every row.
* Real-provider quality and cost comparisons depend on configured credentials, model availability, and non-zero pricing.
* The static profiler is intentionally deterministic and lightweight; dynamic native profilers remain future work.
* New-file/deleted-file unified diff hunks are excluded from V1; existing-file modifications are validated against source context.
* Docker execution depends on a locally available Docker engine and image.
