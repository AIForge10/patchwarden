from .e2b_runner import SandboxHandle, exec_fixed

# Trusted mapping: an alert names a reproducer ID, never a path or a command.
REPRODUCER_TESTS = {
    "checkout_malformed_response": "demo_app/tests/test_incident.py",
    "checkout_unapproved_payment": "demo_app/tests/test_incident_review.py",
    "checkout_unknown_sku": "demo_app/tests/test_incident_inventory.py",
    "checkout_gateway_timeout": "demo_app/tests/test_incident_timeout.py",
}
_REPRODUCERS = {key: ["python", "-m", "pytest", path] for key, path in REPRODUCER_TESTS.items()}


def install_dependencies(handle: SandboxHandle, repo_dir: str = "repo"):
    return exec_fixed(
        handle, ["python", "-m", "pip", "install", "-r", "requirements-dev.txt"], repo_dir
    )


def run_reproducer(handle: SandboxHandle, reproducer_id: str, repo_dir: str = "repo"):
    if reproducer_id not in _REPRODUCERS:
        raise ValueError("unknown reproducer")
    return exec_fixed(handle, _REPRODUCERS[reproducer_id], repo_dir)


def run_regression_suite(handle: SandboxHandle, repo_dir: str = "repo"):
    return exec_fixed(
        handle, ["python", "-m", "pytest", "demo_app/tests/test_baseline.py"], repo_dir
    )


def run_static_checks(handle: SandboxHandle, repo_dir: str = "repo"):
    return exec_fixed(handle, ["python", "-m", "ruff", "check", "."], repo_dir)
