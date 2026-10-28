"""Shared test doubles."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from github import GithubException, UnknownObjectException

from patchwarden import config
from patchwarden.github import client as github_client
from patchwarden.ratelimit import limiter

ROOT = Path(__file__).resolve().parents[1]


class FakeGitHubRepo:
    """In-memory stand-in for the PyGithub Repository calls the publisher makes."""

    default_branch = "main"
    owner = SimpleNamespace(login="acme")

    def __init__(self, base_sha: str = "b" * 40, files: dict | None = None):
        self.base_sha = base_sha
        self.files = files or {"demo_app/app/main.py": ("100644", "old\n")}
        self.refs: dict[str, str] = {}  # branch -> sha
        self.commits: dict[str, dict] = {}  # sha -> {"message", "parents", "files"}
        self.pulls: list[SimpleNamespace] = []
        self.fail_on: str | None = None  # method name that raises a GitHub 403

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise GithubException(403, {"message": "Resource not accessible by integration"})

    def get_git_ref(self, ref: str):
        self._maybe_fail("get_git_ref")
        branch = ref.removeprefix("heads/")
        if branch not in self.refs:
            raise UnknownObjectException(404, {"message": "Not Found"})
        return SimpleNamespace(edit=lambda sha, force=False: self.refs.__setitem__(branch, sha))

    def create_git_ref(self, ref: str, sha: str):
        self._maybe_fail("create_git_ref")
        self.refs[ref.removeprefix("refs/heads/")] = sha

    def get_git_commit(self, sha: str):
        if sha != self.base_sha:
            raise UnknownObjectException(404, {"message": "No commit found for SHA"})
        return SimpleNamespace(sha=sha, tree="base-tree")

    def get_git_tree(self, sha: str, recursive: bool = False):
        items = [SimpleNamespace(path=p, mode=mode) for p, (mode, _) in self.files.items()]
        return SimpleNamespace(tree=items)

    def create_git_tree(self, elements, base_tree):
        self._maybe_fail("create_git_tree")
        assert base_tree == "base-tree"
        return [e._identity for e in elements]  # the JSON PyGithub would send

    def create_git_commit(self, message: str, tree, parents):
        sha = f"c{len(self.commits):039d}"
        files = {e["path"]: (e["mode"], e["content"]) for e in tree}
        self.commits[sha] = {
            "message": message,
            "parents": [p.sha for p in parents],
            "files": files,
        }
        return SimpleNamespace(sha=sha)

    def get_pulls(self, state: str, head: str):
        return [p for p in self.pulls if p.state == state and f"acme:{p.head}" == head]

    def create_pull(self, base: str, head: str, title: str, body: str):
        self._maybe_fail("create_pull")
        url = f"https://github.com/acme/checkout-demo/pull/{len(self.pulls) + 1}"
        pull = SimpleNamespace(
            base=base, head=head, title=title, body=body, state="open", html_url=url
        )
        self.pulls.append(pull)
        return pull


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def disable_tavily(monkeypatch) -> None:
    """Tests never hit Tavily unless they opt in with a fake search_error."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")


@pytest.fixture
def target(tmp_path, monkeypatch):
    """A pinned git repo holding demo_app, allowlisted, with an isolated DB."""
    repo = tmp_path / "checkout-demo"
    shutil.copytree(
        ROOT / "demo_app",
        repo / "demo_app",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "seed"], check=True)
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)

    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(config, "ALLOWED_REPO_URL", str(repo))
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setattr(config, "MAX_PATCH_ATTEMPTS", 3)
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", False)
    monkeypatch.setattr(config, "RUN_DISCOVERY", False)
    monkeypatch.chdir(tmp_path)
    return {"repo_url": str(repo), "sha": sha.strip()}


@pytest.fixture
def fake_github(monkeypatch) -> FakeGitHubRepo:
    repo = FakeGitHubRepo()
    monkeypatch.setattr(github_client, "_repo", lambda: repo)
    return repo
