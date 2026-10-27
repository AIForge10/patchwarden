# Setup guide

Follow these steps once on a new machine. You need git and conda (Miniconda or Anaconda).
The full spec is the project implementation plan PDF (Oct 10–30, 2026).

## 1. Get the code

    git clone https://github.com/AIForge10/resolveloop.git
    cd resolveloop

## 2. Create the environment (Python 3.11 only)

Everyone uses Python 3.11 so that all of us get the exact same package versions.

    conda create -n resolveloop python=3.11 -y
    conda activate resolveloop

Run `conda activate resolveloop` every time you open a new terminal to work on this project.

## 3. Install the packages

    make install

This installs the exact pinned versions from `requirements-dev.txt`, then installs the `resolveloop`
package itself in editable mode (`pip install -e . --no-deps`), so `import resolveloop` works everywhere.

## 4. Add your own keys

    cp .env.example .env

Open `.env` and fill in your own keys. Never commit this file and never paste keys in chat, issues or pull requests.
You don't need every key on day one: Atina's first pieces (demo app, webhook) only need `WEBHOOK_SECRET`.

## 5. Check that it works

    make test      # should show: 1 passed
    make lint      # should show: All checks passed!
    make secrets   # no output = no leaked secrets

Always run commands from inside the `resolveloop` folder.

## Common commands

| Command          | What it does                                                      |
|------------------|-------------------------------------------------------------------|
| `make install`   | Install pinned deps + the package                                 |
| `make test`      | Agent test suite (`tests/`)                                       |
| `make test-demo` | Demo checkout app suite (`demo_app/tests/`)                       |
| `make lint`      | Ruff                                                              |
| `make run`       | Start the API on port 8000 (once `resolveloop/api/main.py` exists)  |
| `make probe`     | Nebius model probe (once `resolveloop/scripts/model_probe.py` exists) |
| `make lock`      | Re-pin after changing dependencies in `pyproject.toml`            |

## Who owns which folder

A = Satyabrata (agent / sandbox / verifier), B = Atina (application / integration). Files are empty placeholders until their owner fills them.

| Path | Owner | Plan piece |
|------|-------|------------|
| `resolveloop/models.py` | Both | Frozen interfaces (day one) |
| `resolveloop/config.py` | A | A2 validated Settings |
| `resolveloop/agent/nebius.py`, `prompts.py`, `context.py`, `patcher.py`, `resolveloop/orchestrator.py` | A | A2, A5 |
| `resolveloop/sandbox/` | A | A3 |
| `resolveloop/verifier/` | A | A4 |
| `resolveloop/discovery/` (except `catalog.py`) | A | A6 |
| `resolveloop/scripts/model_probe.py` | A | A1 |
| `demo_app/` | B | B1 |
| `demo_app/contracts/`, `resolveloop/discovery/catalog.py` | B | B2 |
| `resolveloop/api/`, `store.py`, `security.py`, `events.py`, `resolveloop/scripts/send_demo_alert.py` | B | B3 |
| `resolveloop/agent/research.py` | B | B4 |
| `resolveloop/reporting/` | B | B5 |
| `resolveloop/github/` | B | B6 |
| `resolveloop/ui/` | B | B7 |
| `README.md`, `docs/` | B | B8 |

Working rules (from the plan): one small pull request per feature, branch off `main`, the other person reviews before merge.
Stuck for more than two hours means ask the other.

## Changing packages

`requirements.txt` and `requirements-dev.txt` are lockfiles generated from `pyproject.toml`. To add a package:
add it to `pyproject.toml`, run `make lock`, then `make install`, and commit all three files together.
Tell the other person first, so we stay on the same versions.

## If something goes wrong

- `pip install` fails: check `python --version` shows 3.11 and the `resolveloop` environment is active.
- `ModuleNotFoundError: resolveloop`: run `make install` again (it installs the package in editable mode).
- Still stuck: ask the other person, and write what confused you in `docs/feedback.md`.
