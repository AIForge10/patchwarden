# Setup guide

Follow these steps once on a new machine. You need git and conda (Miniconda or Anaconda).

## 1. Get the code

    git clone https://github.com/<owner>/resolveloop.git
    cd resolveloop

## 2. Create the environment (Python 3.11 only)

Everyone uses Python 3.11 so that all of us get the exact same package versions.

    conda create -n resolveloop python=3.11 -y
    conda activate resolveloop

Run `conda activate resolveloop` every time you open a new terminal to work on this project.

## 3. Install the packages

    pip install -r requirements-dev.txt

This installs the exact pinned versions from the file, so it behaves the same on every machine.

## 4. Add your own keys

    cp .env.example .env

(On Windows PowerShell: `copy .env.example .env`.)

Open `.env` and fill in your own keys. Never commit this file and never paste keys in chat, issues or pull requests.

## 5. Check that it works

    pytest

You should see `1 passed`. Always run commands from inside the `resolveloop` folder.

## Changing packages

The `.txt` requirements files are generated and pinned. If you need a new package, tell Satyabrata before adding it, so we all stay on the same versions.

## If something goes wrong

- `pip install` fails: check `python --version` shows 3.11 and the `resolveloop` environment is active.
- Still stuck for more than two hours: ask Satyabrata, and write what confused you in `docs/feedback_log.md`.
