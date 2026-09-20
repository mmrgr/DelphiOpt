# DelphiOpt v0.1.0

## Included

- Adaptive Delphi multi-agent optimization runtime with budget, correctness, benchmark, trace, report, and reproduction workflows.
- Chinese Windows desktop control plane with high-DPI rendering.
- Advanced settings for budgets, schedulers, Delphi policy, benchmark, sandbox, project commands, and raw YAML.
- Model access manager for OpenAI, OpenAI-compatible, Anthropic, Gemini, and mock endpoints.
- Per-model endpoint, model name, API-key environment variable, timeout, pricing, connectivity test, priority ordering, and failover.
- Evidence-driven candidate feedback, dynamic Python profiling, interleaved benchmark comparisons, bootstrap confidence intervals, outlier filtering, dry-run, analysis-only mode, and cross-platform CI.
- Standalone Windows executable attached to this release.

## Verification

- `51 passed`
- Ruff and Python compilation passed.
- Desktop source and packaged EXE smoke tests passed.
- Custom local OpenAI-compatible endpoint test passed.
- GitHub Actions matrix passed on Ubuntu, Windows, and macOS with Python 3.11 and 3.12.
- Resumable checkpoints, `delphiopt resume`, provider capability checks, bounded concurrent probes, and interactive patch confirmation are included.
- Best-of-N runs issue independent expert requests through a bounded concurrent batch (`scheduler.max_parallel`, default 4).
- Project auto-detection now covers common test layouts and benchmark adapters; accepted patches verify the source has not changed during evaluation and revert partial sync failures.
- The benchmark suite now contains 30 near-real tasks and a budget-matched runner for single, best-of-N, debate, fixed, difficulty, and adaptive Delphi conditions.
- Dynamic profiling now records peak `tracemalloc` memory alongside cProfile hotspot evidence.
- Concurrency-limit, source-change, and rollback coverage passed.
- EXE SHA256: `05726BEC5763DCA295D8ACC8FDA506477233DB0EFEA65CBD327D053BB77D56C5`
