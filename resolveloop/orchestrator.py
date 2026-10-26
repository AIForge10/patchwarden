"""Evidence-gated run coordinator. Owner: Satyabrata.

Runs the gate sequence from plan section 9. Every gate fails closed: when a step
cannot prove its result, the run stops with a failure code instead of claiming success.
"""

import openai

from resolveloop import config
from resolveloop.agent.context import paths_from_traceback, read_context
from resolveloop.agent.nebius_client import ModelUnavailable
from resolveloop.agent.patcher import diagnose, repair_until_verified
from resolveloop.events import emit
from resolveloop.models import IncidentEvidence, RunResult, RunStatus
from resolveloop.sandbox.e2b_runner import create_sandbox, destroy_sandbox
from resolveloop.sandbox.repository import checkout_pinned_repo
from resolveloop.security import assert_allowed_repo
from resolveloop.store import create_run, get_run, set_run_status
from resolveloop.verifier.baseline import capture_baseline, failure_output
from resolveloop.verifier.evidence import build_manifest, write_evidence_bundle

# FAILED is reachable from any state, so it is not listed.
_ALLOWED = {
    RunStatus.RECEIVED: {RunStatus.BASELINING},
    RunStatus.BASELINING: {RunStatus.DIAGNOSING, RunStatus.UNREPRODUCED},
    RunStatus.DIAGNOSING: {RunStatus.PATCHING},
    RunStatus.PATCHING: {RunStatus.VERIFYING},
    RunStatus.VERIFYING: {RunStatus.PATCHING, RunStatus.VERIFIED},
    RunStatus.VERIFIED: {RunStatus.CHALLENGING, RunStatus.PR_OPENED},
    RunStatus.CHALLENGING: {RunStatus.VERIFIED, RunStatus.CONFIRMED_DISCOVERY},
    RunStatus.CONFIRMED_DISCOVERY: {RunStatus.PATCHING},
}


def advance(
    run_id: str,
    next_status: RunStatus,
    message: str = "",
    metadata: dict | None = None,
    severity: str = "info",
) -> None:
    current = get_run(run_id).status
    if next_status != RunStatus.FAILED and next_status not in _ALLOWED.get(current, set()):
        raise ValueError(f"illegal transition {current.value} -> {next_status.value}")
    set_run_status(run_id, next_status)
    emit(run_id, next_status.value, message or f"Entered {next_status.value}", metadata, severity)


def _step(run_id: str, status: RunStatus, message: str, metadata: dict | None = None) -> None:
    """Progress from the repair loop: change state only when the stage changes."""
    if get_run(run_id).status == status:
        emit(run_id, status.value, message, metadata)
    else:
        advance(run_id, status, message, metadata)


def _fail(run_id: str, incident, code: str, message: str, **result) -> RunResult:
    advance(run_id, RunStatus.FAILED, message, {"failure_code": code}, severity="error")
    return RunResult(run_id=run_id, status=RunStatus.FAILED, incident=incident, **result)


def run_incident(incident: IncidentEvidence) -> RunResult:
    run_id = create_run(incident)
    existing = get_run(run_id)
    if existing.status != RunStatus.RECEIVED:
        return existing  # duplicate alert: never repair (or open a PR) twice
    try:
        assert_allowed_repo(incident.repo_url, incident.commit_sha, config)
    except (PermissionError, ValueError) as error:
        return _fail(run_id, incident, "UNAUTHORIZED_REPO", str(error))

    handle = None
    try:
        advance(run_id, RunStatus.BASELINING, "Checking out the pinned commit in a fresh sandbox")
        handle = create_sandbox(run_id)
        checkout_pinned_repo(handle, incident.repo_url, incident.commit_sha)
        baseline = capture_baseline(handle, incident)
        if baseline["reproducer"]["exit_code"] == 124:
            return _fail(run_id, incident, "SANDBOX_TIMEOUT", "Reproducer timed out")
        if not baseline["reproducer_failed"]:
            advance(
                run_id,
                RunStatus.UNREPRODUCED,
                f"Reproducer did not fail with {incident.error_type}; nothing verified to repair",
                {"exit_code": baseline["reproducer"]["exit_code"]},
                severity="warning",
            )
            return RunResult(run_id=run_id, status=RunStatus.UNREPRODUCED, incident=incident)
        if baseline["original_suite"]["exit_code"] != 0:
            message = "Original suite is already red at the pinned commit; cannot judge regressions"
            return _fail(run_id, incident, "VERIFY_FAILED", message)

        advance(
            run_id, RunStatus.DIAGNOSING, f"Baseline red with {incident.error_type}; suite green"
        )
        failure = failure_output(baseline)
        repo = handle.root / "repo"
        diagnosis = diagnose(failure, read_context(repo, paths_from_traceback(failure, repo)))
        emit(run_id, "DIAGNOSING", diagnosis or "No diagnosis; patching from the failure output")

        patch, outcome = repair_until_verified(
            incident,
            handle,
            baseline,
            diagnosis,
            step=lambda status, message, metadata=None: _step(run_id, status, message, metadata),
        )
        if patch is None:
            code = outcome.result.status if outcome else "VERIFY_FAILED"
            message = f"No patch verified within {config.MAX_PATCH_ATTEMPTS} attempts"
            return _fail(
                run_id, incident, code, message, verification=outcome.result if outcome else None
            )

        advance(
            run_id,
            RunStatus.VERIFIED,
            "Reproducer green, original suite green, protected files unchanged",
            {"attempt": patch.attempt},
        )
        result = RunResult(
            run_id=run_id,
            status=RunStatus.VERIFIED,
            incident=incident,
            patch=patch,
            verification=outcome.result,
        )
        commands = [
            {"step": f"baseline_{name}", **{k: baseline[name][k] for k in ("argv", "exit_code")}}
            for name in ("reproducer", "original_suite")
        ] + [
            {"step": f"patched_{name}", "argv": command.argv, "exit_code": command.exit_code}
            for name, command in outcome.commands.items()
        ]
        manifest = build_manifest(result, baseline["test_hashes"], commands)
        manifest["model_id"] = config.NEBIUS_MODEL_REASONING
        result.evidence_path = write_evidence_bundle(run_id, manifest)
        emit(run_id, "VERIFIED", "Evidence written", {"evidence_path": result.evidence_path})
        return maybe_create_pr(result)
    except (ModelUnavailable, openai.OpenAIError) as error:
        return _fail(run_id, incident, "MODEL_UNAVAILABLE", f"{type(error).__name__}: {error}")
    except Exception as error:
        return _fail(run_id, incident, "INTERNAL_ERROR", f"{type(error).__name__}: {error}")
    finally:
        if handle is not None:
            destroy_sandbox(handle)


def maybe_create_pr(result: RunResult) -> RunResult:
    if result.status != RunStatus.VERIFIED or not result.verification:
        return result
    if not all(
        (
            result.verification.reproducer_green,
            result.verification.suite_green,
            result.verification.oracle_intact,
        )
    ):
        return result
    return result
