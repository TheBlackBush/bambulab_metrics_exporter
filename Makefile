.PHONY: test test-unit test-integration test-e2e lint

test:
	.venv/bin/python -m pytest -q

test-unit:
	.venv/bin/python -m pytest -q tests/unit

test-integration:
	.venv/bin/python -m pytest -q tests/integration --no-cov

test-e2e:
	.venv/bin/python -m pytest -q tests/e2e --no-cov

lint:
	.venv/bin/python -m ruff check src tests
