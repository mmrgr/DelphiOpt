# Real-project run recipes

These are reproducible integration targets, not claimed optimization results. Run them from a clean clone, keep the repository's own test suite as the correctness gate, and provide a workload-specific benchmark command before allowing a patch to be written.

## 1. python/pyperformance

`pyperformance` is a real Python benchmark suite with benchmark manifests and a command-line runner. Its documented fast run is:

```powershell
python -m pip install pyperformance
pyperformance run --fast -o baseline.json
```

For DelphiOpt, use a project configuration that points `test_command` at the project's supported test command and `benchmark_command` at a checked-in adapter that emits `{"runtime_ms": ...}`. Keep the pyperformance JSON as an attached external evidence artifact; it is not silently converted to a synthetic fixture.

## 2. psf/pyperf

`pyperf` is a real benchmark toolkit that supports calibrated runs, worker processes, stability checks, JSON output, and memory tracking. A project-local adapter can be run and compared with:

```powershell
python -m pyperf timeit "sorted(range(1000))" -o baseline.json
python -m pyperf stats baseline.json
```

The adapter should expose the exact workload used by the target project and translate its measured result into DelphiOpt's configured benchmark protocol.

## 3. psf/requests

Requests is a real Python library repository with a `tests/` tree and a standard install/test workflow. A local clone can be prepared with:

```powershell
git clone https://github.com/psf/requests.git
cd requests
python -m pip install -e .
python -m pytest -q
```

Because Requests is a library rather than a single benchmark application, the benchmark command must be supplied by the user—for example, a no-network `pyperf` adapter around a selected parsing or request-preparation workload. DelphiOpt then runs that adapter in the same temporary candidate workspace and applies the normal correctness, variance, and performance gates.

No performance number is embedded here: each run records its commit, environment, raw samples, and configured workload in the run trace.
