"""Before-patch evidence: the reproducer must fail for the reported reason. Owner: Satyabrata."""

import hashlib

from patchwarden.sandbox.commands import run_regression_suite, run_reproducer

PROTECTED = (
    "demo_app/tests/test_baseline.py",
    "demo_app/tests/test_incident.py",
    "demo_app/contracts/invariants.json",
)
# Also hashed when present: every other test file and the known-good control gateway.
PROTECTED_GLOBS = ("demo_app/tests/*.py", "demo_app/seed_variants/control/*.py")


def _sha256(handle, path: str) -> str:
    return hashlib.sha256((handle.root / "repo" / path).read_bytes()).hexdigest()


def protected_paths(handle) -> list[str]:
    repo = handle.root / "repo"
    found = {p.relative_to(repo).as_posix() for g in PROTECTED_GLOBS for p in repo.glob(g)}
    return sorted(found | set(PROTECTED))


def is_expected_failure(result, incident) -> bool:
    return result.exit_code != 0 and incident.error_type.lower() in result.stdout.lower()


def capture_baseline(handle, incident) -> dict:
    reproducer = run_reproducer(handle, incident.reproducer_id)
    suite = run_regression_suite(handle)
    return {
        "baseline_sha": incident.commit_sha,
        "reproducer_id": incident.reproducer_id,
        "reproducer_failed": is_expected_failure(reproducer, incident),
        "reproducer": reproducer.model_dump(),
        "original_suite": suite.model_dump(),
        "test_hashes": {path: _sha256(handle, path) for path in protected_paths(handle)},
    }


def failure_output(baseline: dict) -> str:
    """The observed red reproducer output: what the model is shown, not the alert's own trace."""
    return baseline["reproducer"]["stdout"]
