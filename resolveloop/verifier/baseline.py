import hashlib

from resolveloop.sandbox.commands import run_regression_suite, run_reproducer


def _sha256(handle, path: str) -> str:
    return hashlib.sha256((handle.root / "repo" / path).read_bytes()).hexdigest()


def is_expected_failure(result, incident) -> bool:
    return result.exit_code != 0 and incident.error_type.lower() in result.stdout.lower()


def capture_baseline(handle, incident) -> dict:
    reproducer = run_reproducer(handle, incident.reproducer_id)
    suite = run_regression_suite(handle)
    protected = [
        "demo_app/tests/test_baseline.py",
        "demo_app/tests/test_incident.py",
        "demo_app/contracts/invariants.json",
    ]
    return {
        "reproducer_failed": is_expected_failure(reproducer, incident),
        "reproducer": reproducer.model_dump(),
        "original_suite": suite.model_dump(),
        "test_hashes": {path: _sha256(handle, path) for path in protected},
    }
