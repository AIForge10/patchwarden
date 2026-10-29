"""Context step: find the files a traceback names and read them safely. Owner: Satyabrata."""

import difflib
import re
from pathlib import Path

# Matches both Python tracebacks:   File "/x/app/pay.py", line 6, in charge
# and pytest output:                app/pay.py:6: in charge   /   app/pay.py:6: KeyError
_PY_TRACE = re.compile(r'File "([^"]+)", line \d+')
_PYTEST_LINE = re.compile(r"^\s*([\w./\\-]+\.py):\d+", re.M)

_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)

_NEVER_READ = (".env", ".pem", ".key", "secrets")
_SKIP_PARTS = ("site-packages", "/lib/python", "<frozen", ".git/")


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in "/" + path


def paths_from_traceback(traceback: str, repo_root, max_files: int = 5) -> list:
    """Return repo-relative source files named in the traceback (tests excluded).

    A plain assertion failure names only the test. Then the code under test is what
    that test imports from the repo, so follow its imports instead of showing nothing.
    """
    root = Path(repo_root).resolve()
    raw = _PY_TRACE.findall(traceback) + _PYTEST_LINE.findall(traceback)
    found = _source_paths(raw, root)
    if not found:
        tests = [path for path in _repo_paths(raw, root) if _is_test_file(path)]
        found = _source_paths(_imported_paths(tests, root), root)
    return found[:max_files]


def _imported_paths(test_paths: list, root: Path) -> list:
    modules = []
    for test in test_paths:
        for match in _IMPORT.finditer((root / test).read_text(errors="replace")):
            modules.append(match.group(1) or match.group(2))
    paths = []
    for module in modules:
        base = module.replace(".", "/")
        paths += [f"{base}.py", f"{base}/__init__.py"]
    return paths


def _repo_paths(raw: list, root: Path) -> list:
    found = []
    for item in raw:
        if any(part in item for part in _SKIP_PARTS):
            continue
        p = Path(item)
        candidate = (p if p.is_absolute() else root / p).resolve()
        try:
            rel_str = candidate.relative_to(root).as_posix()
        except ValueError:
            continue  # outside the repo
        if candidate.is_file() and rel_str not in found:
            found.append(rel_str)
    return found


def _source_paths(raw: list, root: Path) -> list:
    return [path for path in _repo_paths(raw, root) if not _is_test_file(path)]


def imported_sources(test_path: str, repo_root) -> list:
    """Repo source files that `test_path` imports: how the app is driven from a test."""
    root = Path(repo_root).resolve()
    return _source_paths(_imported_paths([test_path], root), root)


def select_context_paths(traceback: str, repo_root, max_files: int = 5) -> list:
    """Plan name for paths_from_traceback (PDF section 6)."""
    return paths_from_traceback(traceback, repo_root, max_files)


def read_context(repo_root, paths, byte_limit: int = 20000) -> dict:
    """Read the given files (inside the repo only), stopping at byte_limit total."""
    root = Path(repo_root).resolve()
    out, used = {}, 0
    for rel in paths:
        full = (root / rel).resolve()
        if root not in full.parents and full != root:
            continue  # path traversal attempt
        if any(bad in full.name for bad in _NEVER_READ):
            continue
        text = full.read_text(errors="replace")
        if used + len(text) > byte_limit:
            text = text[: max(0, byte_limit - used)] + "\n# ... truncated ...\n"
        out[rel] = text
        used += len(text)
        if used >= byte_limit:
            break
    return out


_FILE_BLOCK = re.compile(r"FILE:\s*(\S+)\s*\n```[a-zA-Z]*\n(.*?)```", re.S)


def parse_model_files(reply_text: str) -> dict:
    """Pull 'FILE: path' + code block pairs out of the model reply. Last one per path wins."""
    return {path: code for path, code in _FILE_BLOCK.findall(reply_text)}


def make_unified_diff(path: str, old: str, new: str) -> str:
    """Build the unified diff ourselves, so the model never has to get hunk numbers right."""
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    out = []
    for line in lines:
        out.append(line)
        if not line.endswith("\n"):
            # File had no final newline: add the standard marker so git apply / patch accept it.
            out.append("\n\\ No newline at end of file\n")
    return "".join(out)
