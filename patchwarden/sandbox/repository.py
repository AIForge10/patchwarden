from .e2b_runner import SandboxHandle, exec_fixed


def checkout_pinned_repo(handle: SandboxHandle, repo_url: str, sha: str) -> str:
    target = handle.root / "repo"
    result = exec_fixed(
        handle, ["git", "clone", "--no-checkout", repo_url, str(target)], timeout_s=180
    )
    if result.exit_code:
        raise RuntimeError(result.stdout)
    result = exec_fixed(
        handle, ["git", "-C", str(target), "checkout", "--detach", sha], timeout_s=60
    )
    if result.exit_code:
        raise RuntimeError(result.stdout)
    return "repo"


def list_source_files(handle: SandboxHandle, repo_dir: str = "repo") -> list[str]:
    root = handle.root / repo_dir
    return sorted(
        str(path.relative_to(root)) for path in root.rglob("*.py") if ".git" not in path.parts
    )


def apply_unified_diff(handle: SandboxHandle, diff: str, repo_dir: str = "repo") -> None:
    if not diff or ".." in diff or " /dev/null" in diff:
        raise ValueError("unsafe diff")
    patch = handle.root / "candidate.diff"
    patch.write_text(diff)
    result = exec_fixed(
        handle, ["git", "-C", str(handle.root / repo_dir), "apply", "--check", str(patch)]
    )
    if result.exit_code:
        raise ValueError(result.stdout)
    result = exec_fixed(handle, ["git", "-C", str(handle.root / repo_dir), "apply", str(patch)])
    if result.exit_code:
        raise RuntimeError(result.stdout)


def reset_to_commit(handle: SandboxHandle, sha: str, repo_dir: str = "repo") -> None:
    result = exec_fixed(handle, ["git", "-C", str(handle.root / repo_dir), "reset", "--hard", sha])
    if result.exit_code:
        raise RuntimeError(result.stdout)
