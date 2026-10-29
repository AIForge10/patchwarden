"""Minimal GitHub publisher; never merges or deploys a change."""

from __future__ import annotations

from github import Github, InputGitTreeElement, UnknownObjectException

from patchwarden import config


def _repo():
    if not (config.GITHUB_TOKEN and config.GITHUB_TARGET_REPO):
        raise RuntimeError("GitHub publishing is not configured")
    name = (
        f"{config.GITHUB_OWNER}/{config.GITHUB_TARGET_REPO}"
        if config.GITHUB_OWNER and "/" not in config.GITHUB_TARGET_REPO
        else config.GITHUB_TARGET_REPO
    )
    return Github(config.GITHUB_TOKEN).get_repo(name)


def create_branch(base_sha: str, run_id: str) -> str:
    branch = f"patchwarden/{run_id}"
    repo = _repo()
    try:
        repo.get_git_ref(f"heads/{branch}")
    except UnknownObjectException:
        repo.create_git_ref(f"refs/heads/{branch}", base_sha)
    return branch


def commit_patch(branch: str, base_sha: str, files: dict[str, str], message: str) -> str:
    """One commit on the pinned SHA holding only the verified files; returns its SHA.

    The branch is PatchWarden's own, so it is force-moved to this commit: a retried
    publish replaces the earlier commit instead of stacking on it.
    """
    if not files:
        raise ValueError("nothing to commit")
    repo = _repo()
    base = repo.get_git_commit(base_sha)
    modes = {item.path: item.mode for item in repo.get_git_tree(base_sha, recursive=True).tree}
    elements = [
        InputGitTreeElement(path, modes.get(path, "100644"), "blob", content=content)
        for path, content in sorted(files.items())
    ]
    tree = repo.create_git_tree(elements, base.tree)
    commit = repo.create_git_commit(message, tree, [base])
    repo.get_git_ref(f"heads/{branch}").edit(commit.sha, force=True)
    return commit.sha


def open_pull_request(branch: str, body: str, title: str = "[PatchWarden] Verified repair") -> str:
    repo = _repo()
    existing = list(repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch}"))
    if existing:
        return existing[0].html_url
    return repo.create_pull(base=repo.default_branch, head=branch, title=title, body=body).html_url
