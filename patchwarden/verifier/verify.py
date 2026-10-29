"""After-patch verifier: the verifier, never the model, sets VERIFIED."""

import shutil
from dataclasses import dataclass, field

from patchwarden.models import CommandResult, VerificationResult
from patchwarden.sandbox.commands import run_regression_suite, run_reproducer
from patchwarden.sandbox.repository import apply_unified_diff, reset_to_commit

from .baseline import _sha256
from .patch_policy import assert_safe_patch

_FEEDBACK_CHARS = 3000  # tail of failing output handed back to the model


@dataclass
class VerifyOutcome:
    result: VerificationResult
    commands: dict[str, CommandResult] = field(default_factory=dict)
    reason: str = ""  # why it did not verify; becomes the next attempt's feedback


def run_verification(handle, baseline: dict, patch) -> VerifyOutcome:
    """Fresh pinned checkout + patch, then reproducer, original suite and protected hashes."""
    red = baseline["reproducer_failed"]
    try:
        assert_safe_patch(patch.unified_diff, baseline["test_hashes"])
        reset_to_commit(handle, baseline["baseline_sha"])
        apply_unified_diff(handle, patch.unified_diff)
    except (ValueError, RuntimeError) as error:
        rejected = VerificationResult(baseline_red=red, status="PATCH_REJECTED")
        return VerifyOutcome(rejected, reason=f"Patch rejected before running tests: {error}")
    # .pyc files are trusted on (mtime seconds, size). A same-size patch applied within the
    # same second would otherwise run the old bytecode and be judged on code it never changed.
    for cache in (handle.root / "repo").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    reproducer = run_reproducer(handle, baseline["reproducer_id"])
    suite = run_regression_suite(handle)
    actual_hashes = {path: _sha256(handle, path) for path in baseline["test_hashes"]}
    intact = actual_hashes == baseline["test_hashes"]
    passed = red and reproducer.exit_code == 0 and suite.exit_code == 0 and intact
    result = VerificationResult(
        baseline_red=red,
        reproducer_green=reproducer.exit_code == 0,
        suite_green=suite.exit_code == 0,
        paths_safe=True,
        oracle_intact=intact,
        status="VERIFIED" if passed else "VERIFY_FAILED",
    )

    reasons = []
    if reproducer.exit_code != 0:
        reasons.append(
            "The incident reproducer still fails:\n" + reproducer.stdout[-_FEEDBACK_CHARS:]
        )
    if suite.exit_code != 0:
        reasons.append("The original test suite now fails:\n" + suite.stdout[-_FEEDBACK_CHARS:])
    if not intact:
        reasons.append("Protected test or contract files changed.")
    commands = {"reproducer": reproducer, "suite": suite}
    return VerifyOutcome(result, commands, "\n\n".join(reasons))


def verify_patch(handle, baseline: dict, patch) -> VerificationResult:
    return run_verification(handle, baseline, patch).result


def verify_discovery_fix(handle, baseline: dict, scenario) -> VerificationResult:
    """Judge a secondary repair against the confirmed oracle plus the original gates.

    The sandbox is assumed to already hold the candidate files. Discovery still cannot
    author assertions: the trusted runner and invariant decide whether the defect holds.
    The orchestrator's second repair loop (--repair-discovery) uses it, so a secondary
    patch is judged the same way as the incident fix.
    """
    from patchwarden.discovery.catalog import load_invariants
    from patchwarden.discovery.runner import evaluate_invariant, execute_scenario

    red = baseline["reproducer_failed"]
    try:
        catalog = load_invariants(handle.root / "repo" / "demo_app/contracts/invariants.json")
        observed = execute_scenario(handle, scenario)
        oracle_holds = not evaluate_invariant(scenario, observed, catalog)
    except Exception:
        return VerificationResult(baseline_red=red, status="ORACLE_UNAVAILABLE")

    reproducer = run_reproducer(handle, baseline["reproducer_id"])
    suite = run_regression_suite(handle)
    actual_hashes = {path: _sha256(handle, path) for path in baseline["test_hashes"]}
    intact = actual_hashes == baseline["test_hashes"]
    passed = red and oracle_holds and reproducer.exit_code == 0 and suite.exit_code == 0 and intact
    return VerificationResult(
        baseline_red=red,
        reproducer_green=reproducer.exit_code == 0,
        suite_green=suite.exit_code == 0,
        paths_safe=True,
        oracle_intact=intact,
        status="VERIFIED" if passed else "VERIFY_FAILED",
    )
