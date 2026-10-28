# Setup guide

Follow these steps once on a new machine. You need git and conda (Miniconda or Anaconda).
The full spec is the project implementation plan PDF (Oct 10–30, 2026).

## 1. Get the code

    git clone https://github.com/AIForge10/patchwarden.git
    cd patchwarden

## 2. Create the environment (Python 3.11 only)

Everyone uses Python 3.11 so that all of us get the exact same package versions.

    conda create -n patchwarden python=3.11 -y
    conda activate patchwarden

Run `conda activate patchwarden` every time you open a new terminal to work on this project.

## 3. Install the packages

    make install

This installs the exact pinned versions from `requirements-dev.txt`, then installs the `patchwarden`
package itself in editable mode (`pip install -e . --no-deps`), so `import patchwarden` works everywhere.

## 4. Add your own keys

    cp .env.example .env

Open `.env` and fill in your own keys. Never commit this file and never paste keys in chat, issues or pull requests.
`WEBHOOK_SECRET` and `ALLOWED_REPO_URL` are enough to start the API and replay recordings. A live repair also needs
`NEBIUS_API_KEY` (model), `E2B_API_KEY` (sandbox; without it code runs in a local temp directory), optionally
`TAVILY_API_KEY` (web hints), and `GITHUB_TOKEN` to open the pull request. On a public host, keep
`OPEN_PR_ON_VERIFIED=false`; set `PUBLIC_DEMO_RUNS_PER_DAY` above 0 to show the "Run live" button.

## 5. Check that it works

    make test      # agent suite: all tests pass, no network (E2B, Nebius, Tavily, GitHub are faked)
    make lint      # should show: All checks passed!
    make secrets   # no output = no leaked secrets

Always run commands from inside the `patchwarden` folder.

## Common commands

| Command          | What it does                                                      |
|------------------|-------------------------------------------------------------------|
| `make install`   | Install pinned deps + the package                                 |
| `make test`      | Agent test suite (`tests/`)                                       |
| `make test-demo` | Demo checkout app suite (`demo_app/tests/`)                       |
| `make lint`      | Ruff                                                              |
| `make run`       | Start the API on port 8000                                        |
| `make probe`     | Nebius model probe                                                |
| `make lock`      | Re-pin after changing dependencies in `pyproject.toml`            |

## Who owns which folder

A = Satyabrata (agent / verifier / orchestrator), B = Atina (demo app / trusted evidence). This is the original day-one split.

| Path | Owner | Plan piece |
|------|-------|------------|
| `patchwarden/models.py` | Both | Frozen interfaces (day one) |
| `patchwarden/config.py` | A | A2 validated Settings |
| `patchwarden/agent/nebius.py`, `prompts.py`, `context.py`, `patcher.py`, `patchwarden/orchestrator.py` | A | A2, A5 |
| `patchwarden/sandbox/` | A | A3 |
| `patchwarden/verifier/` | A | A4 |
| `patchwarden/discovery/` (except `catalog.py`) | A | A6 |
| `patchwarden/scripts/model_probe.py` | A | A1 |
| `demo_app/` | B | B1 |
| `demo_app/contracts/`, `patchwarden/discovery/catalog.py` | B | B2 |
| `patchwarden/api/`, `store.py`, `security.py`, `events.py`, `patchwarden/scripts/send_demo_alert.py` | B | B3 |
| `patchwarden/agent/research.py` | B | B4 |
| `patchwarden/reporting/` | B | B5 |
| `patchwarden/github/` | B | B6 |
| `patchwarden/ui/` | B | B7 |
| `README.md`, `docs/` | B | B8 |

Working rules (from the plan): one small pull request per feature, branch off `main`, the other person reviews before merge.
Stuck for more than two hours means ask the other.

## Changing packages

`requirements.txt` and `requirements-dev.txt` are lockfiles generated from `pyproject.toml`. To add a package:
add it to `pyproject.toml`, run `make lock`, then `make install`, and commit all three files together.
Tell the other person first, so we stay on the same versions.

## If something goes wrong

- `pip install` fails: check `python --version` shows 3.11 and the `patchwarden` environment is active.
- `ModuleNotFoundError: patchwarden`: run `make install` again (it installs the package in editable mode).
- Still stuck: ask the other person, and write what confused you in `docs/feedback.md`.
