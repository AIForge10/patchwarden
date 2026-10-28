"""GitHub publisher against an in-memory repo: no network, no token."""

import pytest
from github import GithubException

from patchwarden import config
from patchwarden.github import client

BASE = "b" * 40


def test_commit_lands_on_pinned_sha_with_only_verified_files(fake_github) -> None:
    fake_github.files["demo_app/app/run.sh"] = ("100755", "#!/bin/sh\n")
    branch = client.create_branch(BASE, "run-1")
    sha = client.commit_patch(
        branch, BASE, {"demo_app/app/main.py": "new\n", "demo_app/app/run.sh": "x\n"}, "fix"
    )

    commit = fake_github.commits[sha]
    assert branch == "patchwarden/run-1" and fake_github.refs[branch] == sha
    assert commit["parents"] == [BASE]
    assert commit["files"] == {
        "demo_app/app/main.py": ("100644", "new\n"),
        "demo_app/app/run.sh": ("100755", "x\n"),  # existing file mode is kept
    }


def test_republish_replaces_the_commit_instead_of_stacking(fake_github) -> None:
    branch = client.create_branch(BASE, "run-1")
    client.commit_patch(branch, BASE, {"demo_app/app/main.py": "one\n"}, "fix")
    assert client.create_branch(BASE, "run-1") == branch  # existing branch reused
    second = client.commit_patch(branch, BASE, {"demo_app/app/main.py": "two\n"}, "fix")

    assert fake_github.refs[branch] == second
    assert fake_github.commits[second]["parents"] == [BASE]


def test_commit_refuses_empty_change(fake_github) -> None:
    with pytest.raises(ValueError):
        client.commit_patch("patchwarden/run-1", BASE, {}, "fix")


def test_open_pull_request_is_idempotent(fake_github) -> None:
    first = client.open_pull_request("patchwarden/run-1", "body", title="[PatchWarden] t")
    second = client.open_pull_request("patchwarden/run-1", "body", title="[PatchWarden] t")

    assert first == second and len(fake_github.pulls) == 1
    assert fake_github.pulls[0].base == "main"


def test_auth_errors_are_not_mistaken_for_a_missing_branch(fake_github) -> None:
    fake_github.fail_on = "get_git_ref"
    with pytest.raises(GithubException):
        client.create_branch(BASE, "run-1")
    assert fake_github.refs == {}


def test_unconfigured_publisher_refuses(monkeypatch) -> None:
    monkeypatch.setattr(config, "GITHUB_TOKEN", "")
    with pytest.raises(RuntimeError, match="not configured"):
        client.create_branch(BASE, "run-1")
