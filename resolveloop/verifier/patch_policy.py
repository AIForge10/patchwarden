"""Deterministic policy that prevents a proposed patch from changing its judges."""

from pathlib import PurePosixPath

PROTECTED_PREFIXES = ("demo_app/tests/", "demo_app/contracts/", ".github/")
PROTECTED_FILES = {"pyproject.toml", "requirements.txt", "requirements-dev.txt"}


def parse_changed_paths(diff: str) -> list[str]:
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
            if path != "/dev/null":
                paths.append(path)
    return paths


def assert_safe_patch(diff: str, protected_hashes: dict | None = None) -> None:
    forbidden = ("GIT binary patch", "new file mode", "deleted file mode", "rename ")
    if not diff or any(marker in diff for marker in forbidden):
        raise ValueError("patch contains unsupported file operation")
    paths = parse_changed_paths(diff)
    if not paths:
        raise ValueError("patch contains no changed files")
    for path in paths:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or path.startswith(".env"):
            raise ValueError(f"unsafe patch path: {path}")
        if not path.startswith("demo_app/app/") or path.endswith(".py") is False:
            raise ValueError(f"patch path is not an allowed source file: {path}")
        if path.startswith(PROTECTED_PREFIXES) or path in PROTECTED_FILES:
            raise ValueError(f"patch touches protected path: {path}")
