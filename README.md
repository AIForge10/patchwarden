# ResolveLoop

ResolveLoop is an evidence-gated incident-response prototype. It accepts a signed, allowlisted alert, preserves an append-only event trail, and is designed to open a human-review pull request only after independent verification.

## Local check

```sh
conda activate resolveloop
make install
make test
make lint
make secrets
python -m pytest demo_app/tests/test_baseline.py
python -m pytest demo_app/tests/test_incident.py  # intentionally RED on the seeded baseline
```

Copy `.env.example` to `.env` and set `WEBHOOK_SECRET`, `ALLOWED_REPO_URL`, and the service credentials before starting the API with `make run`. The demo contains a disclosed seeded defect; it never auto-merges or deploys repairs.
