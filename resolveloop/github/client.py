"""Minimal GitHub publisher; never merges or deploys a change."""

from __future__ import annotations

from github import Github

from resolveloop import config


def _repo():
    if not (config.GITHUB_TOKEN and config.GITHUB_TARGET_REPO):
        raise RuntimeError("GitHub publishing is not configured")
    return Github(config.GITHUB_TOKEN).get_repo(config.GITHUB_TARGET_REPO)


def create_branch(base_sha: str, run_id: str) -> str:
    branch = f"resolveloop/{run_id}"
    repo = _repo()
    try:
        repo.get_git_ref(f"heads/{branch}")
    except Exception:
        repo.create_git_ref(f"refs/heads/{branch}", base_sha)
    return branch


def open_pull_request(branch: str, body: str) -> str:
    repo = _repo()
    existing = list(repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch}"))
    if existing:
        return existing[0].html_url
    return repo.create_pull(
        title="[ResolveLoop] Verified repair", body=body, head=branch, base=repo.default_branch
    ).html_url
