from resolveloop.models import VerificationResult
from resolveloop.sandbox.commands import run_regression_suite, run_reproducer

from .baseline import _sha256
from .patch_policy import assert_safe_patch


def verify_patch(handle, baseline: dict, patch) -> VerificationResult:
    try:
        assert_safe_patch(patch.unified_diff, baseline["test_hashes"])
    except ValueError:
        return VerificationResult(
            baseline_red=baseline["reproducer_failed"], status="PATCH_REJECTED"
        )
    reproducer = run_reproducer(handle, "checkout_malformed_response")
    suite = run_regression_suite(handle)
    actual_hashes = {path: _sha256(handle, path) for path in baseline["test_hashes"]}
    intact = actual_hashes == baseline["test_hashes"]
    passed = (
        baseline["reproducer_failed"]
        and reproducer.exit_code == 0
        and suite.exit_code == 0
        and intact
    )
    return VerificationResult(
        baseline_red=baseline["reproducer_failed"],
        reproducer_green=reproducer.exit_code == 0,
        suite_green=suite.exit_code == 0,
        paths_safe=True,
        oracle_intact=intact,
        status="VERIFIED" if passed else "VERIFY_FAILED",
    )


def verify_discovery_fix(handle, baseline: dict, scenario) -> VerificationResult:
    return verify_patch(handle, baseline, scenario)
