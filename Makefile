test:
	python -m pytest --cov=delphiopt --cov-report=term-missing --cov-fail-under=80 -q

lint:
	python -m ruff check src tests analysis

typecheck:
	python -m mypy src
