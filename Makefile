# Run inside the conda env:  conda activate patchwarden
.PHONY: install hooks lock lint format test test-demo run serve probe incident evaluation record secrets

install: hooks      ## install pinned deps + this package (editable)
	pip install -r requirements-dev.txt
	pip install -e . --no-deps

hooks:              ## use .githooks/ (commit-msg blocks AI co-author trailers)
	git config core.hooksPath .githooks

lock:               ## re-pin after editing pyproject.toml dependencies
	pip-compile --strip-extras -o requirements.txt pyproject.toml
	pip-compile --strip-extras --extra dev -o requirements-dev.txt pyproject.toml

lint:
	ruff check .

format:
	ruff format .

test:
	python -m pytest

test-demo:          ## demo app: original suite + control green; the four test_incident*.py are RED by design
	python -m pytest demo_app/tests/test_baseline.py demo_app/tests/test_control.py
	-python -m pytest -q demo_app/tests/test_incident*.py

run:
	uvicorn patchwarden.api.main:app --reload --port 8000

serve:              ## bind 0.0.0.0 (Docker / hosted). PORT defaults to 8000.
	uvicorn patchwarden.api.main:app --host 0.0.0.0 --port $${PORT:-8000}

probe:              ## Nebius model probe (A1)
	python -m patchwarden.scripts.model_probe

incident:           ## one incident end to end (real model; opens a PR if OPEN_PR_ON_VERIFIED + GitHub set)
	python -m patchwarden.scripts.run_incident --fixture $(or $(FIXTURE),demo_app/fixtures/incident_01.json)

evaluation:         ## rebuild docs/evaluation.csv and docs/evaluation_models.csv from the listed runs
	python -m patchwarden.scripts.build_evaluation docs/evaluation/cases.json
	python -m patchwarden.scripts.build_evaluation docs/evaluation/models.json --csv docs/evaluation_models.csv

record:             ## export a run for UI replay: make record RUN=run-...
	python -m patchwarden.scripts.record_run $(RUN)

secrets:            ## scan tracked files for leaked secrets
	git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline  # pragma: allowlist secret
