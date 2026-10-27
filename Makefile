# Run inside the conda env:  conda activate resolveloop
.PHONY: install lock lint format test test-demo run serve probe incident record secrets

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

serve:              ## bind 0.0.0.0 (Docker / hosted). PORT defaults to 8000.
	uvicorn resolveloop.api.main:app --host 0.0.0.0 --port $${PORT:-8000}

probe:              ## Nebius model probe (A1)
	python -m resolveloop.scripts.model_probe

incident:           ## one incident end to end (real model; opens a PR if OPEN_PR_ON_VERIFIED + GitHub set)
	python -m resolveloop.scripts.run_incident

record:             ## export a run for UI replay: make record RUN=run-...
	python -m resolveloop.scripts.record_run $(RUN)

secrets:            ## scan tracked files for leaked secrets
	git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline  # pragma: allowlist secret
