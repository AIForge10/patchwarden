"""A2 + A3 check: traceback + file -> diff, then the same call again to prove the cache.

Run from the project root:
    python resolveloop/scripts/day_one/try_agent.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root: day_one -> scripts -> resolveloop -> repo
sys.path.insert(0, str(ROOT))

from resolveloop.agent.context import read_context, select_context_paths
from resolveloop.agent.nebius_client import healthcheck_model
from resolveloop.agent.patcher import diagnose, propose_patch

HERE = Path(__file__).resolve().parent


def main() -> None:
    failing = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
        cwd=HERE, capture_output=True, text=True,
    ).stdout

    print("--- healthcheck:", healthcheck_model())

    files = read_context(HERE, select_context_paths(failing, HERE))
    diagnosis = diagnose(failing, files)
    print("--- diagnosis:\n" + (diagnosis or "(empty: reply cut off or wrong format)"))

    for attempt in (1, 2):
        p = propose_patch(failing, HERE, diagnosis=diagnosis)
        r = p.reply
        print(f"--- call {attempt}: cached={r.cached} finish={r.finish_reason} "
              f"tokens in/out={r.prompt_tokens}/{r.completion_tokens} files_read={p.paths_read}")
        if p.diff:
            print(p.diff)
        else:
            print("NO DIFF:", p.problem)


if __name__ == "__main__":
    main()