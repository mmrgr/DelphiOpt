# Benchmarking and ablation

`BenchmarkEngine` performs budgeted warmups and repeated samples, reports runtime, throughput, peak reported memory, mean, median, standard deviation, and a 95% normal-approximation interval. A benchmark may emit `{"runtime_ms": ..., "memory_mb": ...}` for application-level measurements; otherwise wall-clock command time is used. Partial evidence caused by budget exhaustion is rejected.

Compile, optional lint, and correctness tests run first. Failed candidates are retained in the trace but excluded from performance ranking. Acceptance requires configured median speedup, conservative confidence-interval speedup, and coefficient-of-variation stability. The demo uses a held-out workload and deterministic answer check. Real projects can provide any test and benchmark commands through `delphiopt.yaml`.

`analysis/run_ablation.py` runs every combination of `single`, `debate`, `delphi` and `fixed`, `difficulty`, `adaptive_voi` against fresh copies. Its output is marked `simulation: true` because Mock Provider evidence is not a real-LLM experiment. No result is hard-coded.
