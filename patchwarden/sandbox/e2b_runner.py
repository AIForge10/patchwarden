"""Ephemeral sandbox: a local pinned checkout plus, when configured, an E2B microVM.

The agent reads and patches the pinned checkout in a disposable local directory; git
never executes repository code. Every command that does run repository code (pytest and
the trusted scenario runner) executes inside an E2B sandbox whose network egress is
limited to PyPI, after the current checkout is copied in. With SANDBOX_BACKEND=local (or
no E2B key) the same fixed argv runs in a local subprocess, which is how offline tests run.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patchwarden import config
from patchwarden.models import CommandResult

REMOTE_HOME = "/home/user"
REMOTE_TRUSTED = f"{REMOTE_HOME}/trusted"
REMOTE_WORK = f"{REMOTE_HOME}/work"
# Pinned to demo_app/pyproject.toml; installed by trusted code, never read from the checkout.
DEMO_DEPENDENCIES = ("fastapi==0.143.0", "httpx==0.28.1", "pydantic==2.14.0", "pytest==9.1.1")
PYPI_HOSTS = ["pypi.org", "files.pythonhosted.org"]
# The trusted scenario runner and the models it imports, copied in outside the checkout.
TRUSTED_MODULES = ("__init__.py", "models.py", "discovery/__init__.py", "discovery/runner.py")
SANDBOX_LIFETIME_SECONDS = 3600
_CODE_RUNNERS = {"python", "python3"}
_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache"}
_OUTPUT_LIMIT = 20_000


@dataclass
class SandboxHandle:
    run_id: str
    root: Path
    remote: Any = None  # e2b.Sandbox when repository code runs in E2B

    @property
    def backend(self) -> str:
        return "e2b" if self.remote is not None else "local"

    def describe(self) -> dict:
        if self.remote is None:
            return {"backend": "local"}
        return {
            "backend": "e2b",
            "sandbox_id": self.remote.sandbox_id,
            "egress_allowlist": PYPI_HOSTS,
        }


def use_e2b() -> bool:
    if config.SANDBOX_BACKEND == "local":
        return False
    if config.SANDBOX_BACKEND == "e2b" and not config.E2B_API_KEY:
        raise RuntimeError("SANDBOX_BACKEND=e2b requires E2B_API_KEY")
    return bool(config.E2B_API_KEY)


def create_sandbox(run_id: str) -> SandboxHandle:
    handle = SandboxHandle(
        run_id=run_id, root=Path(tempfile.mkdtemp(prefix=f"patchwarden-{run_id}-"))
    )
    if use_e2b():
        try:
            handle.remote = _create_remote(run_id)
        except Exception:
            shutil.rmtree(handle.root, ignore_errors=True)
            raise
    return handle


def _create_remote(run_id: str):
    from e2b import Sandbox

    sandbox = Sandbox.create(
        timeout=SANDBOX_LIFETIME_SECONDS,
        metadata={"app": "patchwarden", "run_id": run_id},
        network={"allow_out": PYPI_HOSTS, "deny_out": ["0.0.0.0/0"]},
        api_key=config.E2B_API_KEY,
    )
    try:
        sandbox.commands.run(
            shlex.join(["python", "-m", "pip", "install", "--quiet", *DEMO_DEPENDENCIES]),
            timeout=240,
        )
        package = Path(__file__).resolve().parents[1]
        trusted = f"{REMOTE_TRUSTED}/patchwarden"
        sandbox.files.write_files(
            [
                {"path": f"{trusted}/{name}", "data": (package / name).read_bytes()}
                for name in TRUSTED_MODULES
            ]
        )
    except Exception:
        sandbox.kill()
        raise
    return sandbox


def exec_fixed(
    handle: SandboxHandle, argv: list[str], cwd: str = ".", timeout_s: int = 180
) -> CommandResult:
    if not argv or argv[0] in {"sh", "bash", "zsh"}:
        raise ValueError("shell execution is not allowed")
    if handle.remote is not None and argv[0] in _CODE_RUNNERS:
        return _exec_remote(handle, argv, cwd, timeout_s)
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
    return _result(argv, exit_code, stdout, stderr, started)


def _exec_remote(handle: SandboxHandle, argv: list[str], cwd: str, timeout_s: int):
    from e2b import CommandExitException, TimeoutException

    started = time.monotonic()
    remote_cwd = _sync_checkout(handle, cwd)
    try:
        completed = handle.remote.commands.run(
            shlex.join(argv),
            cwd=remote_cwd,
            envs={"PYTHONPATH": REMOTE_TRUSTED, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=timeout_s,
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.exit_code
    except CommandExitException as error:
        stdout, stderr, exit_code = error.stdout, error.stderr, error.exit_code
    except TimeoutException:
        stdout, stderr, exit_code = "", "timeout", 124
    return _result(argv, exit_code, stdout, stderr, started)


def _sync_checkout(handle: SandboxHandle, cwd: str) -> str:
    """Replace the remote copy with the current local checkout (patched or clean)."""
    local = handle.root / cwd
    remote = f"{REMOTE_WORK}/{cwd}".rstrip("/.")
    files = [
        {"path": f"{remote}/{path.relative_to(local).as_posix()}", "data": path.read_bytes()}
        for path in sorted(local.rglob("*"))
        if path.is_file() and not _SKIP_PARTS.intersection(path.relative_to(local).parts)
    ]
    handle.remote.commands.run(shlex.join(["rm", "-rf", remote]))
    handle.remote.files.write_files(files)
    return remote


def _result(argv, exit_code: int, stdout: str, stderr: str, started: float) -> CommandResult:
    output = (stdout or "") + (stderr or "")
    return CommandResult(
        argv=argv,
        exit_code=exit_code,
        stdout=output[:_OUTPUT_LIMIT],
        stderr="",
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=len(output) > _OUTPUT_LIMIT,
    )


def destroy_sandbox(handle: SandboxHandle) -> None:
    if handle.remote is not None:
        try:
            handle.remote.kill()
        except Exception:
            pass  # the sandbox lifetime cap still reclaims it
    shutil.rmtree(handle.root, ignore_errors=True)
