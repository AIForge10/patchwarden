"""Disposable local sandbox adapter used for deterministic development verification.

The interface deliberately accepts only fixed argv vectors; production deployments
can replace this handle with E2B without changing verifier call sites.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from patchwarden.models import CommandResult


@dataclass
class SandboxHandle:
    run_id: str
    root: Path


def create_sandbox(run_id: str) -> SandboxHandle:
    return SandboxHandle(
        run_id=run_id, root=Path(tempfile.mkdtemp(prefix=f"patchwarden-{run_id}-"))
    )


def exec_fixed(
    handle: SandboxHandle, argv: list[str], cwd: str = ".", timeout_s: int = 180
) -> CommandResult:
    if not argv or argv[0] in {"sh", "bash", "zsh"}:
        raise ValueError("shell execution is not allowed")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=handle.root / cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or "", error.stderr or "timeout", 124
    limit = 20_000
    output = (stdout + stderr)[:limit]
    return CommandResult(
        argv=argv,
        exit_code=exit_code,
        stdout=output,
        stderr="",
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=len(stdout + stderr) > limit,
    )


def destroy_sandbox(handle: SandboxHandle) -> None:
    shutil.rmtree(handle.root, ignore_errors=True)
