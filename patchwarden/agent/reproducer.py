"""Write the incident reproducer from the alert when none ships with the repo. Owner: Satyabrata.

The model writes one pytest file; trusted code saves it at a fixed path and accepts it only if,
at the pinned commit and inside the sandbox, it fails with the reported error type at the exact
file and line the alert's stack trace names. Once accepted it is an ordinary protected test:
hashed with the others, so no patch can weaken it, and shipped in the PR as the regression test.
"""

from __future__ import annotations

import ast
import re

from patchwarden import config
from patchwarden.agent.context import (
    imported_sources,
    parse_model_files,
    paths_from_traceback,
    read_context,
)
from patchwarden.agent.nebius_client import chat_full
from patchwarden.agent.prompts import REPRODUCER_SYSTEM, build_reproducer_prompt
from patchwarden.models import RunStatus
from patchwarden.sandbox.commands import REPRODUCER_TESTS, SYNTHESIZED_REPRODUCER, run_reproducer
from patchwarden.verifier.baseline import pytest_summary

EXAMPLE_TEST = "demo_app/tests/test_baseline.py"  # shows the model how tests drive the app
MAX_TEST_BYTES = 8000
_FRAME = re.compile(r'File "([^"]+)", line (\d+)')
_FEEDBACK_CHARS = 2000


def crash_site(traceback: str, repo_root) -> tuple[str, int] | None:
    """The deepest stack frame in a repository source file: where the alert says it crashed."""
    sources = set(paths_from_traceback(traceback, repo_root, max_files=50))
    frames = [(path, int(line)) for path, line in _FRAME.findall(traceback) if path in sources]
    return frames[-1] if frames else None


def _static_problem(source: str) -> str:
    if len(source.encode()) > MAX_TEST_BYTES:
        return "The test file is too long."
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return f"The test file does not parse: {error}"
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test") for n in tree.body):
        return "The file has no test function."
    if "pytest.raises" in source or re.search(r"^\s*raise\b", source, re.M):
        return "The test must let the application raise; it may not raise or expect the error."
    return ""


def _rejection(result, error_type: str, site: tuple[str, int]) -> str:
    """Why this run of the candidate does not reproduce the alert, or "" if it does."""
    path, line = site
    if result.exit_code == 0:
        return "The test passes on the buggy commit, so it does not reproduce the crash."
    if f"{path}:{line}: {error_type}" not in result.stdout:
        return (
            f"The test did not fail with {error_type} at {path}:{line}. Its output:\n"
            + result.stdout[-_FEEDBACK_CHARS:]
        )
    return ""


def write_reproducer(incident, handle, step, tries: int = 2) -> str | None:
    """Return the accepted test source (saved in the checkout), or None if none was accepted."""
    repo = handle.root / "repo"
    path = REPRODUCER_TESTS[SYNTHESIZED_REPRODUCER]
    site = crash_site(incident.traceback, repo)
    if site is None:
        step(
            RunStatus.BASELINING, "Cannot write a reproducer: the stack trace names no source line"
        )
        return None
    error_type = incident.error_type.split(".")[-1]
    context = paths_from_traceback(incident.traceback, repo) + imported_sources(EXAMPLE_TEST, repo)
    files = read_context(repo, list(dict.fromkeys(context)))
    example = (repo / EXAMPLE_TEST).read_text()
    model = config.NEBIUS_MODEL_REASONING
    feedback = ""
    for attempt in range(1, tries + 1):
        info = {"reproducer_try": attempt, "model": model}
        step(
            RunStatus.BASELINING,
            f"No reproducer shipped with the alert: {model} is writing one from the stack trace "
            f"(try {attempt} of {tries})",
            info,
        )
        prompt = build_reproducer_prompt(incident, path, files, example, feedback)
        reply = chat_full(prompt, system=REPRODUCER_SYSTEM, model=model, max_tokens=4000)
        written = parse_model_files(reply.text) if reply.finish_reason != "length" else {}
        source = written.get(path) or (next(iter(written.values())) if len(written) == 1 else "")
        problem = _static_problem(source) if source else "The reply held no test file."
        if not problem:
            (repo / path).write_text(source)
            result = run_reproducer(handle, SYNTHESIZED_REPRODUCER)
            problem = _rejection(result, error_type, site)
        if not problem:
            tally = pytest_summary(result.stdout) or "failed"
            step(
                RunStatus.BASELINING,
                f"Model-written reproducer accepted: fails with {error_type} at "
                f"{site[0]}:{site[1]}, the line the alert names ({tally})",
                info | {"path": path},
            )
            return source
        (repo / path).unlink(missing_ok=True)
        step(
            RunStatus.BASELINING,
            f"Model-written reproducer rejected: {problem.splitlines()[0]}",
            info,
        )
        feedback = problem
    return None
