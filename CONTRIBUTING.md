# Contributing

## Development setup

```powershell
python -m pip install -e ".[dev]"
python -m ruff check src tests analysis benchmarks/generate_tasks.py
python -m mypy src
python -m pytest --cov=delphiopt --cov-report=term-missing --cov-fail-under=80 -q
```

## Pull requests

Keep changes focused, add a regression test for behavior changes, and include the exact benchmark command and configuration when changing optimization decisions. Do not commit API keys, generated `.delphiopt` runs, or build output.
