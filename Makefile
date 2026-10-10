# Run inside the conda env:  conda activate resolveloop
.PHONY: install lock lint format test test-demo run probe secrets

install:            ## install pinned deps + this package (editable)
	pip install -r requirements-dev.txt
	pip install -e . --no-deps

lock:               ## re-pin after editing pyproject.toml dependencies
	pip-compile --strip-extras -o requirements.txt pyproject.toml
	pip-compile --strip-extras --extra dev -o requirements-dev.txt pyproject.toml

lint:
	ruff check .

format:
	ruff format .

test:
	python -m pytest

test-demo:          ## demo app suite (test_incident is expected RED on the seeded baseline)
	python -m pytest demo_app/tests

run:
	uvicorn resolveloop.api.main:app --reload --port 8000

probe:              ## Nebius model probe (A1) - implement resolveloop/scripts/model_probe.py first
	python -m resolveloop.scripts.model_probe

secrets:            ## scan tracked files for leaked secrets
	git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline  # pragma: allowlist secret
