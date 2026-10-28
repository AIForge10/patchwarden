"""Step 3: ask the model to fix the throwaway bug, and apply + test its answer.

Run from the project root:
    python scripts/day_one/run_day_one.py            # model sees the code
    python scripts/day_one/run_day_one.py --trace-only   # model sees ONLY the stack trace

It shows you the model's reply, and you decide by hand if the fix is right.
It does NOT edit your files: it writes the model's version to a temp copy and
runs the tests against that copy.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from openai import OpenAI  # noqa: E402

HERE = Path(__file__).resolve().parent
BUGGY = HERE / "buggy_checkout.py"


def run_tests(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
        cwd=folder,
        capture_output=True,
        text=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-only", action="store_true")
    args = ap.parse_args()

    if not (config.NEBIUS_API_KEY and config.NEBIUS_BASE_URL and config.NEBIUS_MODEL_REASONING):
        sys.exit("Fill NEBIUS_API_KEY, NEBIUS_BASE_URL and NEBIUS_MODEL_REASONING in .env first.")

    # 1. Reproduce the failure and capture the real stack trace.
    before = run_tests(HERE)
    print("=== Tests BEFORE the fix ===")
    print(before.stdout[-1500:])
    trace = before.stdout

    # 2. Build the prompt.
    code = BUGGY.read_text()
    if args.trace_only:
        evidence = f"Failing test output / stack trace:\n{trace}"
    else:
        evidence = (
            f"Failing test output / stack trace:\n{trace}\n\nSource file buggy_checkout.py:\n{code}"
        )
    prompt = (
        "A Python test fails. Fix the bug with the smallest change. "
        "Reply with ONLY the full corrected contents of buggy_checkout.py "
        "inside one ```python code block. Do not change the tests.\n\n" + evidence
    )

    client = OpenAI(api_key=config.NEBIUS_API_KEY, base_url=config.NEBIUS_BASE_URL)
    reply = client.chat.completions.create(
        model=config.NEBIUS_MODEL_REASONING,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8000,
    )
    text = reply.choices[0].message.content or ""
    finish = reply.choices[0].finish_reason
    print("=== Model reply ===")
    print(text)
    print(f"\n[finish_reason: {finish}]")
    if finish == "length":
        print(
            "NOTE: the reply was cut off by the token limit (the model used it up while thinking)."
        )

    # The model may think out loud and show code several times. The answer is the LAST block.
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    if not blocks:
        print("\nRESULT: NO CODE BLOCK (reply cut off or not in the requested format).")
        return
    match_text = textwrap.dedent(blocks[-1])

    # 3. Test the model's version in a temp copy (your files stay untouched).
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        shutil.copy(HERE / "test_checkout.py", tmpdir)
        (tmpdir / "buggy_checkout.py").write_text(match_text)
        after = run_tests(tmpdir)
    print("=== Tests AFTER the model's fix ===")
    print(after.stdout[-1500:])
    print("RESULT:", "FIXED" if after.returncode == 0 else "NOT FIXED")


if __name__ == "__main__":
    main()
