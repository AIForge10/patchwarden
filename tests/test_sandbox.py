"""E2B routing: repository code runs remotely on a fresh copy; git stays local. No network."""

from types import SimpleNamespace

import pytest
from e2b import CommandExitException, TimeoutException

from patchwarden import config
from patchwarden.sandbox import e2b_runner
from patchwarden.sandbox.e2b_runner import SandboxHandle, exec_fixed, use_e2b


class FakeRemote:
    sandbox_id = "sbx-test"

    def __init__(self, raise_on_run=None):
        self.raise_on_run = raise_on_run
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(write_files=self._write)
        self.runs: list[tuple[str, dict]] = []
        self.written: list[str] = []
        self.killed = False

    def _run(self, cmd, **kwargs):
        self.runs.append((cmd, kwargs))
        if cmd.startswith("python") and self.raise_on_run:
            raise self.raise_on_run
        return SimpleNamespace(stdout="ok\n", stderr="", exit_code=0)

    def _write(self, files):
        self.written = [entry["path"] for entry in files]

    def kill(self):
        self.killed = True


def _handle(tmp_path, remote) -> SandboxHandle:
    repo = tmp_path / "repo"
    (repo / "demo_app/app/__pycache__").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "demo_app/app/main.py").write_text("x = 1\n")
    (repo / "demo_app/app/__pycache__/main.pyc").write_bytes(b"stale")
    (repo / ".git/config").write_text("[core]\n")
    return SandboxHandle(run_id="t", root=tmp_path, remote=remote)


def test_python_runs_remotely_on_a_fresh_copy_without_git_or_bytecode(tmp_path) -> None:
    remote = FakeRemote()
    result = exec_fixed(_handle(tmp_path, remote), ["python", "-m", "pytest", "x.py"], "repo")

    assert result.exit_code == 0 and result.stdout == "ok\n"
    assert remote.written == ["/home/user/work/repo/demo_app/app/main.py"]
    (wipe, _), (command, kwargs) = remote.runs
    assert wipe == "rm -rf /home/user/work/repo"
    assert command == "python -m pytest x.py" and kwargs["cwd"] == "/home/user/work/repo"
    assert kwargs["envs"]["PYTHONPATH"] == "/home/user/trusted"


def test_git_stays_local(tmp_path) -> None:
    remote = FakeRemote()
    result = exec_fixed(_handle(tmp_path, remote), ["git", "--version"])
    assert result.exit_code == 0 and remote.runs == []


@pytest.mark.parametrize(
    ("error", "code"),
    [(CommandExitException("boom", "out", 1, "exit status 1"), 1), (TimeoutException("slow"), 124)],
)
def test_remote_failures_map_to_exit_codes(tmp_path, error, code) -> None:
    handle = _handle(tmp_path, FakeRemote(raise_on_run=error))
    assert exec_fixed(handle, ["python", "-c", "pass"], "repo").exit_code == code


def test_shell_is_refused_even_remotely(tmp_path) -> None:
    with pytest.raises(ValueError):
        exec_fixed(_handle(tmp_path, FakeRemote()), ["bash", "-c", "id"], "repo")


def test_backend_selection(monkeypatch) -> None:
    monkeypatch.setattr(config, "E2B_API_KEY", "")
    monkeypatch.setattr(config, "SANDBOX_BACKEND", "auto")
    assert use_e2b() is False
    monkeypatch.setattr(config, "E2B_API_KEY", "e2b_test")
    assert use_e2b() is True
    monkeypatch.setattr(config, "SANDBOX_BACKEND", "local")
    assert use_e2b() is False
    monkeypatch.setattr(config, "E2B_API_KEY", "")
    monkeypatch.setattr(config, "SANDBOX_BACKEND", "e2b")
    with pytest.raises(RuntimeError):
        use_e2b()


def test_destroy_kills_the_remote_and_removes_the_workspace(tmp_path) -> None:
    remote = FakeRemote()
    handle = _handle(tmp_path / "ws", remote)
    e2b_runner.destroy_sandbox(handle)
    assert remote.killed and not handle.root.exists()
