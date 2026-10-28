"""Tests for canonical data models and schema round-trip serialization."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from resolveloop.models import (
    CommandResult,
    DiscoveryResult,
    IncidentEvidence,
    PatchCandidate,
    RunEvent,
    RunResult,
    RunStatus,
    ScenarioSpec,
    VerificationResult,
)


def test_run_status_enum() -> None:
    expected_statuses = {
        "RECEIVED",
        "BASELINING",
        "UNREPRODUCED",
        "DIAGNOSING",
        "PATCHING",
        "VERIFYING",
        "CHALLENGING",
        "CONFIRMED_DISCOVERY",
        "VERIFIED",
        "FAILED",
        "PR_OPENED",
    }
    actual_statuses = {status.value for status in RunStatus}
    assert actual_statuses == expected_statuses
    assert str(RunStatus.RECEIVED) == "RECEIVED"
    assert RunStatus("VERIFIED") == RunStatus.VERIFIED


def test_incident_evidence_round_trip() -> None:
    now = datetime.now(UTC)
    incident = IncidentEvidence(
        incident_id="demo-001",
        repo_url="https://github.com/AIForge10/checkout-demo",
        commit_sha="a" * 40,
        error_type="TypeError",
        message="Unexpected payment response",
        traceback="Traceback (most recent call last):\n  File 'app.py', line 10...",
        reproducer_id="checkout_malformed_response",
        sanitized_request={"order_id": "order-123", "amount": 50},
        timestamp=now,
        environment={"provider_mode": "malformed"},
    )
    json_str = incident.model_dump_json()
    restored = IncidentEvidence.model_validate_json(json_str)

    assert restored.incident_id == incident.incident_id
    assert restored.repo_url == incident.repo_url
    assert restored.commit_sha == incident.commit_sha
    assert restored.sanitized_request == {"order_id": "order-123", "amount": 50}
    assert restored.environment == {"provider_mode": "malformed"}
    assert restored.timestamp == now


def test_incident_evidence_validation() -> None:
    with pytest.raises(ValidationError):
        # Missing required fields
        IncidentEvidence(
            incident_id="demo-001",
            repo_url="https://github.com/AIForge10/checkout-demo",
        )  # type: ignore[call-arg]


def test_run_event_defaults_and_round_trip() -> None:
    event = RunEvent(
        run_id="run-123",
        seq=1,
        stage="BASELINING",
        message="Checking baseline reproducer",
        metadata={"reproducer_id": "checkout_malformed_response"},
    )
    assert event.severity == "info"
    assert isinstance(event.created_at, datetime)

    restored = RunEvent.model_validate_json(event.model_dump_json())
    assert restored.run_id == "run-123"
    assert restored.seq == 1
    assert restored.stage == "BASELINING"
    assert restored.metadata == {"reproducer_id": "checkout_malformed_response"}


def test_patch_candidate_round_trip() -> None:
    diff = (
        "--- a/demo_app/app/main.py\n"
        "+++ b/demo_app/app/main.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    patch = PatchCandidate(
        base_sha="b" * 40,
        unified_diff=diff,
        rationale="Handle malformed gateway payload",
        attempt=2,
        touched_paths=["demo_app/app/main.py"],
    )
    restored = PatchCandidate.model_validate_json(patch.model_dump_json())
    assert restored.base_sha == "b" * 40
    assert restored.attempt == 2
    assert restored.touched_paths == ["demo_app/app/main.py"]


def test_command_result_defaults_and_round_trip() -> None:
    cmd = CommandResult(argv=["pytest", "tests/"], exit_code=0, stdout="3 passed")
    assert cmd.stderr == ""
    assert cmd.duration_ms == 0
    assert not cmd.truncated

    restored = CommandResult.model_validate_json(cmd.model_dump_json())
    assert restored.argv == ["pytest", "tests/"]
    assert restored.exit_code == 0
    assert restored.stdout == "3 passed"


def test_verification_result_defaults_and_round_trip() -> None:
    default_vr = VerificationResult()
    assert not default_vr.baseline_red
    assert not default_vr.reproducer_green
    assert not default_vr.suite_green
    assert default_vr.status == "FAILED"

    verified = VerificationResult(
        baseline_red=True,
        reproducer_green=True,
        suite_green=True,
        paths_safe=True,
        oracle_intact=True,
        test_counts={"passed": 4, "failed": 0},
        status="VERIFIED",
    )
    restored = VerificationResult.model_validate_json(verified.model_dump_json())
    assert restored.baseline_red is True
    assert restored.reproducer_green is True
    assert restored.suite_green is True
    assert restored.status == "VERIFIED"
    assert restored.test_counts == {"passed": 4, "failed": 0}


def test_scenario_spec_and_discovery_result_round_trip() -> None:
    spec = ScenarioSpec(
        scenario_id="retry_same_key",
        invariant_id="at_most_one_charge",
        params={"attempts": 3},
        rationale="Verify charge idempotency",
    )
    discovery = DiscoveryResult(
        scenario=spec,
        oracle_id="at_most_one_charge",
        observed={"charges": 2},
        violated=True,
        reproduced_twice=True,
        baseline_commit="c" * 40,
    )
    restored = DiscoveryResult.model_validate_json(discovery.model_dump_json())
    assert restored.scenario.scenario_id == "retry_same_key"
    assert restored.oracle_id == "at_most_one_charge"
    assert restored.violated is True
    assert restored.reproduced_twice is True
    assert restored.observed == {"charges": 2}


def test_run_result_full_round_trip() -> None:
    incident = IncidentEvidence(
        incident_id="demo-001",
        repo_url="https://github.com/AIForge10/checkout-demo",
        commit_sha="a" * 40,
        error_type="ValidationError",
        message="Unexpected payment response",
        traceback="Traceback ...",
        reproducer_id="checkout_malformed_response",
    )
    patch = PatchCandidate(
        base_sha="a" * 40,
        unified_diff="--- a\n+++ b\n",
        rationale="Fix validation error",
        attempt=1,
        touched_paths=["demo_app/app/main.py"],
    )
    verification = VerificationResult(
        baseline_red=True,
        reproducer_green=True,
        suite_green=True,
        paths_safe=True,
        oracle_intact=True,
        status="VERIFIED",
    )
    spec = ScenarioSpec(
        scenario_id="normal_success",
        invariant_id="success_exactly_one_order",
        params={"amount": 10},
    )
    discovery = DiscoveryResult(
        scenario=spec,
        oracle_id="success_exactly_one_order",
        observed={"orders": 1},
        violated=False,
        reproduced_twice=False,
    )
    event = RunEvent(run_id="run-001", seq=1, stage="VERIFIED", message="All gates passed")

    run_result = RunResult(
        run_id="run-001",
        status=RunStatus.PR_OPENED,
        incident=incident,
        patch=patch,
        verification=verification,
        discoveries=[discovery],
        events=[event],
        evidence_path="evidence/run-001.json",
        pr_url="https://github.com/AIForge10/checkout-demo/pull/1",
    )

    json_str = run_result.model_dump_json()
    restored = RunResult.model_validate_json(json_str)

    assert restored.run_id == "run-001"
    assert restored.status == RunStatus.PR_OPENED
    assert restored.incident.incident_id == "demo-001"
    assert restored.patch is not None and restored.patch.attempt == 1
    assert restored.verification is not None and restored.verification.status == "VERIFIED"
    assert len(restored.discoveries) == 1
    assert restored.discoveries[0].violated is False
    assert len(restored.events) == 1
    assert restored.evidence_path == "evidence/run-001.json"
    assert restored.pr_url == "https://github.com/AIForge10/checkout-demo/pull/1"

    # Verify model_copy works immutably
    updated = restored.model_copy(update={"status": RunStatus.FAILED})
    assert updated.status == RunStatus.FAILED
    assert restored.status == RunStatus.PR_OPENED
