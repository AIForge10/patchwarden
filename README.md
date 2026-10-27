# ResolveLoop

ResolveLoop is an evidence-gated incident-response prototype. It accepts a signed, allowlisted alert, preserves an append-only event trail, and is designed to open a human-review pull request only after independent verification.

## Local check

```sh
conda activate resolveloop
make install      # also enables .githooks/ (blocks AI co-author trailers)
make test
make lint
make secrets
python -m pytest demo_app/tests/test_baseline.py
python -m pytest demo_app/tests/test_incident.py  # intentionally RED on the seeded baseline
```

Copy `.env.example` to `.env` and set `WEBHOOK_SECRET`, `ALLOWED_REPO_URL`, and the service credentials before starting the API with `make run`. The demo contains a disclosed seeded defect; it never auto-merges or deploys repairs.

## Hosted demo

```sh
docker build -t resolveloop .
docker run --rm -p 8000:8000 --env-file .env resolveloop
```

`GET /health` must return `"ok": true`. Keep `OPEN_PR_ON_VERIFIED=false` on the public URL until the final judged run that should open a human-review pull request.
