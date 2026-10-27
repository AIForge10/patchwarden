import pytest

from resolveloop.agent.context import make_unified_diff
from resolveloop.discovery.catalog import load_invariants
from resolveloop.models import PatchCandidate, ScenarioSpec
from resolveloop.sandbox.e2b_runner import create_sandbox, destroy_sandbox
from resolveloop.sandbox.repository import apply_unified_diff, checkout_pinned_repo
from resolveloop.verifier.baseline import capture_baseline
from resolveloop.verifier.patch_policy import assert_safe_patch, parse_changed_paths
from resolveloop.verifier.verify import run_verification, verify_discovery_fix
from tests.test_orchestrator import BUG, FIX, MAIN, _commit_variant, _incident

SAFE = "--- a/demo_app/app/main.py\n+++ b/demo_app/app/main.py\n@@ -1 +1 @@\n-a\n+b\n"


def test_patch_policy_permits_only_application_python() -> None:
    assert parse_changed_paths(SAFE) == ["demo_app/app/main.py"]
    assert_safe_patch(SAFE)
    with pytest.raises(ValueError):
        assert_safe_patch(SAFE.replace("demo_app/app/main.py", "demo_app/tests/test_incident.py"))


def _sandbox(target):
    handle = create_sandbox("verify")
    checkout_pinned_repo(handle, target["repo_url"], target["sha"])
    return handle


def _candidate(diff: str, sha: str) -> PatchCandidate:
    return PatchCandidate(base_sha=sha, unified_diff=diff, touched_paths=["demo_app/app/main.py"])


def test_verifier_accepts_red_to_green_with_hashes_unchanged(target) -> None:
    handle = _sandbox(target)
    try:
        incident = _incident(target)
        baseline = capture_baseline(handle, incident)
        assert baseline["reproducer_failed"]
        diff = make_unified_diff("demo_app/app/main.py", MAIN, FIX)
        outcome = run_verification(handle, baseline, _candidate(diff, target["sha"]))
        assert outcome.result.status == "VERIFIED"
        assert outcome.result.reproducer_green and outcome.result.suite_green
        assert outcome.result.oracle_intact
    finally:
        destroy_sandbox(handle)


def test_verifier_rejects_a_fix_that_breaks_the_original_suite(target) -> None:
    handle = _sandbox(target)
    try:
        baseline = capture_baseline(handle, _incident(target))
        broken = MAIN.replace(BUG, '    return create_order(request.order_id, "failed")\n')
        diff = make_unified_diff("demo_app/app/main.py", MAIN, broken)
        outcome = run_verification(handle, baseline, _candidate(diff, target["sha"]))
        assert outcome.result.status == "VERIFY_FAILED"
        assert outcome.result.reproducer_green and not outcome.result.suite_green
        assert "original test suite now fails" in outcome.reason
    finally:
        destroy_sandbox(handle)


def test_verifier_rejects_protected_test_edits_before_running(target) -> None:
    handle = _sandbox(target)
    try:
        baseline = capture_baseline(handle, _incident(target))
        diff = (
            "--- a/demo_app/tests/test_incident.py\n+++ b/demo_app/tests/test_incident.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        outcome = run_verification(handle, baseline, _candidate(diff, target["sha"]))
        assert outcome.result.status == "PATCH_REJECTED"
        assert "rejected before running tests" in outcome.reason.lower()
    finally:
        destroy_sandbox(handle)


def test_verifier_fails_closed_if_protected_hashes_do_not_match(target) -> None:
    handle = _sandbox(target)
    try:
        baseline = capture_baseline(handle, _incident(target))
        hashes = {**baseline["test_hashes"], "demo_app/tests/test_baseline.py": "0"}
        baseline["test_hashes"] = hashes
        diff = make_unified_diff("demo_app/app/main.py", MAIN, FIX)
        outcome = run_verification(handle, baseline, _candidate(diff, target["sha"]))
        assert outcome.result.status == "VERIFY_FAILED"
        assert not outcome.result.oracle_intact
        assert "Protected test or contract files changed" in outcome.reason
    finally:
        destroy_sandbox(handle)


def test_discovery_fix_stays_green_when_the_oracle_holds(target) -> None:
    handle = _sandbox(target)
    try:
        baseline = capture_baseline(handle, _incident(target))
        apply_unified_diff(handle, make_unified_diff("demo_app/app/main.py", MAIN, FIX))
        spec = ScenarioSpec(
            scenario_id="retry_same_key",
            invariant_id="at_most_one_charge",
            params={"attempts": 2},
        )
        catalog = load_invariants(handle.root / "repo" / "demo_app/contracts/invariants.json")
        assert spec.scenario_id in catalog["invariants"][spec.invariant_id]["scenario_ids"]
        result = verify_discovery_fix(handle, baseline, spec)
        assert result.status == "VERIFIED"
        assert result.reproducer_green and result.suite_green
    finally:
        destroy_sandbox(handle)


def test_discovery_fix_fails_when_the_second_defect_remains(target) -> None:
    sha = _commit_variant(
        target,
        "demo_app/app/payments.py",
        "    if idempotency_key not in _charges:\n        _charges[idempotency_key] = 1\n",
        "    _charges[idempotency_key] = _charges.get(idempotency_key, 0) + 1\n",
    )
    handle = create_sandbox("verify-secondary")
    checkout_pinned_repo(handle, target["repo_url"], sha)
    try:
        baseline = capture_baseline(handle, _incident(target, commit_sha=sha))
        apply_unified_diff(handle, make_unified_diff("demo_app/app/main.py", MAIN, FIX))
        spec = ScenarioSpec(
            scenario_id="retry_same_key",
            invariant_id="at_most_one_charge",
            params={"attempts": 2},
        )
        result = verify_discovery_fix(handle, baseline, spec)
        assert result.status == "VERIFY_FAILED"
        assert result.reproducer_green and result.suite_green
    finally:
        destroy_sandbox(handle)
