.PHONY: test test-unit test-integration test-e2e test-profile lint

test:
	.venv/bin/python -m pytest -q

test-unit:
	.venv/bin/python -m pytest -q tests/unit

test-integration:
	.venv/bin/python -m pytest -q tests/integration --no-cov

test-e2e:
	.venv/bin/python -m pytest -q tests/e2e --no-cov

test-profile:
	@echo "[test-profile] deterministic smoke profile"
	$(MAKE) test-integration
	$(MAKE) test-e2e
	@echo "[test-profile] OK"

lint:
	.venv/bin/python -m ruff check src tests
