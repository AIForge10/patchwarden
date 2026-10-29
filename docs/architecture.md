# Architecture

PatchWarden turns one signed incident alert into, at most, one human-review pull request.
The model proposes; trusted code decides. Every claim in the run state, the evidence
bundle and the PR comes from a deterministic check, never from model output.

## Sequence

```
signed alert ──► POST /webhooks/incident   HMAC, allowlisted repo, exact 40-hex SHA, known reproducer
                   │  202 + run_id; a duplicate incident_id returns the same run and starts nothing
                   ▼  (background task)
RECEIVED ─► BASELINING      fresh E2B sandbox + local workspace, detached checkout of the pinned SHA,
             │               hash protected files, run the reproducer + original suite (in E2B)
             ├─► UNREPRODUCED   reproducer not red for the reported error type: stop, no model call
             ▼
           DIAGNOSING        model sees the OBSERVED red output, the source files it names,
             │               and optional untrusted Tavily hints (fail-open if search fails)
             ▼
           PATCHING ⇄ VERIFYING   up to MAX_PATCH_ATTEMPTS, each from a clean pinned checkout;
             │                     verifier output is the next attempt's feedback;
             │                     optional NEBIUS_PATCH_MODELS ladder: a rejected patch
             │                     moves the next attempt to a larger model
             ├─► FAILED (VERIFY_FAILED / PATCH_REJECTED / MODEL_UNAVAILABLE / SANDBOX_TIMEOUT …)
             ▼
           VERIFIED          reproducer green, original suite green, protected hashes unchanged
             ▼  (RUN_DISCOVERY)
           CHALLENGING ─► CONFIRMED_DISCOVERY ─► VERIFIED   (experimental, see below)
                              └─► PATCHING ⇄ VERIFYING ─► VERIFIED   (REPAIR_DISCOVERY, plan P2)
             ▼
           evidence/<run_id>.json
             ▼  (OPEN_PR_ON_VERIFIED)
           PR_OPENED         branch patchwarden/<run_id> on the pinned SHA, one commit, PR to default branch
```

Illegal transitions raise (`orchestrator._ALLOWED`); FAILED is reachable from any state and
always carries a `failure_code`. The sandbox is destroyed in a `finally` block.

## Sandbox

`sandbox/e2b_runner.py` gives every run two disposable places:

- **A local workspace** holding the pinned checkout. The agent reads source files and git
  applies patches here. git never executes repository code.
- **An E2B microVM** (when `E2B_API_KEY` is set; `SANDBOX_BACKEND=auto`). Every command that
  runs repository code (pytest and the trusted scenario runner) executes there, on a fresh
  copy of the current checkout. Network egress is limited to `pypi.org` and
  `files.pythonhosted.org` for the pinned demo dependencies; GitHub, Nebius and every other
  host are unreachable from inside. No key or token is ever sent into the sandbox. The
  trusted runner and models module are copied to `/home/user/trusted`, outside the checkout.

The sandbox ID and egress allowlist are recorded in the evidence manifest. Both are torn
down in a `finally` block; the E2B lifetime cap (1 hour) reclaims a sandbox if the process
dies. `SANDBOX_BACKEND=local` runs the same fixed argv in a local subprocess: offline tests
use it, and so does a machine without an E2B key.

## Trust boundaries

| Untrusted | Trusted |
|---|---|
| Webhook payload, model output, repository content, test stdout, web search | Pinned human-authored tests, `contracts/invariants.json` and the known-good control gateway, their SHA-256 hashes, `patch_policy`, the reproducer-ID → test mapping and fixed argv in `sandbox/commands.py`, the verifier, the scenario runner and invariant checks |

- The model never writes a diff: it returns full file contents for files it was shown, and
  PatchWarden builds the diff. Only `demo_app/app/**/*.py` may change; tests, contracts, CI,
  lockfiles, `.env*`, new/deleted/renamed/binary files are rejected before anything runs.
- The verifier resets to the pinned SHA and applies the patch itself, clears bytecode caches,
  then runs the reproducer and original suite and re-hashes protected files.
- Event messages and metadata are redacted (`security.redact_text`) before storage, so the API,
  UI and recordings only ever see redacted text.
- The GitHub token is used only by `github/client.py`, only after VERIFIED, and never reaches
  the sandbox.

## Discovery (A6, experimental)

After the core repair is verified, the model picks up to `MAX_SCENARIOS` scenarios from the
human-authored catalog: scenario ID, invariant ID and bounded parameters only
(`discovery/scenarios.py`). `catalog.validate_scenario` rejects anything else, and the
rejection is logged. Accepted scenarios run through `discovery/runner.py` as a subprocess
whose working directory is the patched sandbox checkout, so they exercise the code under
review, not PatchWarden's own copy. A trusted invariant judges each run. A violation counts
as confirmed only when (1) it reproduces twice from a reset state and (2) the same scenario
**holds** when the runner swaps in the known-good control gateway
(`demo_app/seed_variants/control/payments.py`, outside the patchable tree). The second check
is the negative control: an oracle that also fires on correct code is not trusted, and the
violation is logged as `DISCOVERY_UNCONFIRMED` instead of being claimed.

Discovery can never fail or downgrade a verified repair. Model or runner problems end as
`DISCOVERY_UNCONFIRMED` / `ORACLE_UNAVAILABLE` events and the run returns to VERIFIED.
By default a confirmed defect is reported in the PR's "Additional scenarios" table as
**unresolved**, and the PR carries only the verified incident fix. With
`REPAIR_DISCOVERY=true` (or `run_incident --repair-discovery`) the second repair loop (plan
P2) runs: up to `MAX_PATCH_ATTEMPTS` patches on top of the verified fix, each judged by
`verifier.verify_discovery_fix` (confirmed oracle now holds, original reproducer green, suite
green, protected hashes intact). Only then does the combined diff ship; otherwise the first
verified patch ships alone (plan section 9, branch rule).

## Publishing (A7)

`orchestrator.maybe_create_pr` requires VERIFIED with baseline red, reproducer green, suite
green and oracle intact. It commits the exact verified file contents onto the pinned SHA
(file modes preserved). A retried publish force-moves PatchWarden's own branch instead of
stacking commits, and `open_pull_request` returns an existing open PR rather than opening a
second one. If GitHub fails, the run stays VERIFIED with its evidence and a `GITHUB_ERROR`
event. It never claims PR_OPENED without a URL. PatchWarden never merges or deploys.

## Progress UI (A7)

`make run`, then open `http://127.0.0.1:8000/` (redirects to `/ui/`).

- Live: `/ui/?run=<run_id>` polls `GET /runs/{id}` and `GET /runs/{id}/events?after=<seq>`,
  and shows `GET /runs/{id}/evidence` once the bundle exists.
- Replay: `python -m patchwarden.scripts.record_run <run_id>` (or `make record RUN=…`) exports
  the stored run, events and evidence to `patchwarden/ui/recordings/`. Then open
  `/ui/?replay=recordings/<run_id>.json` (add `&speed=2` to play faster), or use
  "Play recording". The UI renders only stored data, as text. A PR link is shown only for a
  PR_OPENED run.

`pr_url` and `evidence_path` on `GET /runs/{id}` are read back from the event log, which is
the source of truth.

## Hosted endpoint

The API is a single Docker image (`Dockerfile`) that serves `/ui/`, `/health`, and the
signed webhook. Hosts must inject env vars; the image never contains `.env`.

```sh
docker build -t patchwarden .
docker run --rm -p 8000:8000 --env-file .env patchwarden
# then GET http://127.0.0.1:8000/health  →  {"ok": true, ...}
```

`make serve` binds `0.0.0.0` and `PORT` (default 8000) for the same process without Docker.
Required to boot: `WEBHOOK_SECRET`, `ALLOWED_REPO_URL`. Nebius and GitHub keys stay optional
so the UI can replay recordings on a host that is not yet wired to the model.

On a public URL set `OPEN_PR_ON_VERIFIED=false`. A hosted instance that can sign alerts and
has a GitHub token would otherwise open a real PR.

### Public live demo (`api/demo.py`)

`GET /demo` lists the six bundled alerts and whether live runs are available; `POST /demo/runs`
with `{"case": "01"}`…`"06"` starts one. The visitor chooses a case number and nothing else:
the alert is read from `demo_app/fixtures/` (copied into the image as data) and goes through the
same gates as a signed alert, under a fresh `…-live-<random>` incident ID. Guards, all fail-closed:

| Guard | Response |
|---|---|
| `PUBLIC_DEMO_RUNS_PER_DAY=0` (default) | 403, button disabled with the reason |
| `OPEN_PR_ON_VERIFIED=true` | 403: public runs must never open PRs |
| no E2B key (`use_e2b()` false) | 403: repository code must not run in the web server |
| model not configured | 403 |
| a live run already in progress | 409 with `X-Run-Id`, so the UI opens that run instead |
| daily cap reached (UTC day, in memory) | 429 |

Case 02 turns on the second repair loop for that run only (`run_incident(..., repair_discovery=True)`),
without touching the global setting. `GET /health` reports the model ID, sandbox backend, whether
Tavily and GitHub are configured, and whether the live demo is on, never secret values.

## One command

```sh
python -m patchwarden.scripts.run_incident          # ALLOWED_REPO_URL at its current HEAD
python -m patchwarden.scripts.run_incident --sha <40-hex>
```

This uses the real model. It opens a real PR on `GITHUB_TARGET_REPO` when
`OPEN_PR_ON_VERIFIED=true` and `GITHUB_TOKEN` is set. `ALLOWED_REPO_URL` and
`GITHUB_TARGET_REPO` must be the same repository, or the commit lookup fails and the run
records `GITHUB_ERROR`.

## Decisions to verify (plan section 18)

| Item | Status |
|---|---|
| Nebius base URL and model IDs | Verified Oct 21 with `healthcheck_model()` (see `docs/feedback.md`) |
| E2B | Verified Oct 28 with e2b SDK 2.53.1: `Sandbox.create(network={"allow_out": [...], "deny_out": ["0.0.0.0/0"]})` blocks all egress but PyPI; non-zero exit raises `CommandExitException`, timeouts raise `TimeoutException` (mapped to exit 124) |
| GitHub fine-grained token | Contents + Pull requests read/write on the demo repo only. Live PRs opened on `Satyabratadas/patchwarden-demo` (see `docs/evaluation.md`) |
| Hosted endpoint | Docker image on Northflank: https://p01--patchwarden-api--smbsdvp245v8.code.run (`/health`, `/ui/`). Runs with `OPEN_PR_ON_VERIFIED=false` so a public URL cannot open PRs |
| Tavily | Wired into diagnosis as untrusted hints; HTTPS results only; search failures skip to the observed failure and source files. The query is built from the observed failure (library + exception + failing call, or `python <builtin> <alert message>`), redacted, and logged in the run's events. Citations land in the evidence manifest and PR body |
