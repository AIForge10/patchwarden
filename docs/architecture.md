# Architecture

ResolveLoop turns one signed incident alert into, at most, one human-review pull request.
The model proposes; trusted code decides. Every claim in the run state, the evidence
bundle and the PR comes from a deterministic check, never from model output.

## Sequence

```
signed alert ──► POST /webhooks/incident   HMAC, allowlisted repo, exact 40-hex SHA, known reproducer
                   │  202 + run_id; a duplicate incident_id returns the same run and starts nothing
                   ▼  (background task)
RECEIVED ─► BASELINING      fresh sandbox, detached checkout of the pinned SHA, hash protected files,
             │               run the reproducer + original suite
             ├─► UNREPRODUCED   reproducer not red for the reported error type: stop, no model call
             ▼
           DIAGNOSING        model sees the OBSERVED red output + the source files it names
             ▼
           PATCHING ⇄ VERIFYING   up to MAX_PATCH_ATTEMPTS, each from a clean pinned checkout;
             │                     verifier output is the next attempt's feedback
             ├─► FAILED (VERIFY_FAILED / PATCH_REJECTED / MODEL_UNAVAILABLE / SANDBOX_TIMEOUT …)
             ▼
           VERIFIED          reproducer green, original suite green, protected hashes unchanged
             ▼  (RUN_DISCOVERY)
           CHALLENGING ─► CONFIRMED_DISCOVERY ─► VERIFIED   (experimental, see below)
             ▼
           evidence/<run_id>.json
             ▼  (OPEN_PR_ON_VERIFIED)
           PR_OPENED         branch resolveloop/<run_id> on the pinned SHA, one commit, PR to default branch
```

Illegal transitions raise (`orchestrator._ALLOWED`); FAILED is reachable from any state and
always carries a `failure_code`. The sandbox is destroyed in a `finally` block.

## Trust boundaries

| Untrusted | Trusted |
|---|---|
| Webhook payload, model output, repository content, test stdout, web search | Pinned human-authored tests and `contracts/invariants.json`, their SHA-256 hashes, `patch_policy`, the fixed argv in `sandbox/commands.py`, the verifier, the scenario runner and invariant checks |

- The model never writes a diff: it returns full file contents for files it was shown, and
  ResolveLoop builds the diff. Only `demo_app/app/**/*.py` may change; tests, contracts, CI,
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
review, not ResolveLoop's own copy. A trusted invariant judges each run. A violation counts
as confirmed only when it reproduces twice from a reset state.

Discovery can never fail or downgrade a verified repair. Model or runner problems end as
`DISCOVERY_UNCONFIRMED` / `ORACLE_UNAVAILABLE` events and the run returns to VERIFIED.
The second repair loop (plan P2) is not built. A confirmed defect is reported in the
PR's "Additional scenarios" table as **unresolved**, and the PR carries only the verified
incident fix (plan section 9, branch rule).

## Publishing (A7)

`orchestrator.maybe_create_pr` requires VERIFIED with baseline red, reproducer green, suite
green and oracle intact. It commits the exact verified file contents onto the pinned SHA
(file modes preserved). A retried publish force-moves ResolveLoop's own branch instead of
stacking commits, and `open_pull_request` returns an existing open PR rather than opening a
second one. If GitHub fails, the run stays VERIFIED with its evidence and a `GITHUB_ERROR`
event. It never claims PR_OPENED without a URL. ResolveLoop never merges or deploys.

## Progress UI (A7)

`make run`, then open `http://127.0.0.1:8000/` (redirects to `/ui/`).

- Live: `/ui/?run=<run_id>` polls `GET /runs/{id}` and `GET /runs/{id}/events?after=<seq>`,
  and shows `GET /runs/{id}/evidence` once the bundle exists.
- Replay: `python -m resolveloop.scripts.record_run <run_id>` (or `make record RUN=…`) exports
  the stored run, events and evidence to `resolveloop/ui/recordings/`. Then open
  `/ui/?replay=recordings/<run_id>.json` (add `&speed=2` to play faster), or use
  "Play recording". The UI renders only stored data, as text. A PR link is shown only for a
  PR_OPENED run.

`pr_url` and `evidence_path` on `GET /runs/{id}` are read back from the event log, which is
the source of truth.

## One command

```sh
python -m resolveloop.scripts.run_incident          # ALLOWED_REPO_URL at its current HEAD
python -m resolveloop.scripts.run_incident --sha <40-hex>
```

This uses the real model. It opens a real PR on `GITHUB_TARGET_REPO` when
`OPEN_PR_ON_VERIFIED=true` and `GITHUB_TOKEN` is set. `ALLOWED_REPO_URL` and
`GITHUB_TARGET_REPO` must be the same repository, or the commit lookup fails and the run
records `GITHUB_ERROR`.

## Decisions to verify (plan section 18)

| Item | Status |
|---|---|
| Nebius base URL and model IDs | Verified Oct 21 with `healthcheck_model()` (see `docs/feedback.md`) |
| E2B | Not used yet: `sandbox/e2b_runner.py` is a local disposable-directory adapter with the same interface |
| GitHub fine-grained token | Needs Contents + Pull requests read/write on the demo repo only; not yet exercised against the real API |
| Tavily | Not wired into diagnosis yet |
