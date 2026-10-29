# Setup guide

Follow these steps once on a new machine. You need git and conda (Miniconda or Anaconda).

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
`TAVILY_API_KEY` (web hints), and `GITHUB_TOKEN` to open the pull request. On a public host, set
`PUBLIC_DEMO_RUNS_PER_DAY` above 0 to show the "Run live" button. Public runs open PRs only with
`PUBLIC_DEMO_OPEN_PRS=true`, `OPEN_PR_ON_VERIFIED=true` and a token scoped to the demo repository;
otherwise keep `OPEN_PR_ON_VERIFIED=false`. `NEBIUS_PATCH_MODELS` turns on the Nano → Super → Ultra
patch ladder.

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

## Changing packages

`requirements.txt` and `requirements-dev.txt` are lockfiles generated from `pyproject.toml`. To add a package:
add it to `pyproject.toml`, run `make lock`, then `make install`, and commit all three files together.

## If something goes wrong

- `pip install` fails: check `python --version` shows 3.11 and the `patchwarden` environment is active.
- `ModuleNotFoundError: patchwarden`: run `make install` again (it installs the package in editable mode).
- Still stuck: open an issue on the repository.
