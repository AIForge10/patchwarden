"""Evidence-gated run coordinator. Owner: Satyabrata.

Runs the gate sequence from plan section 9. Every gate fails closed: when a step
cannot prove its result, the run stops with a failure code instead of claiming success.
"""

import json

import openai

from resolveloop import config
from resolveloop.agent.context import paths_from_traceback, read_context
from resolveloop.agent.nebius_client import ModelUnavailable
from resolveloop.agent.patcher import diagnose, repair_until_verified
from resolveloop.discovery.catalog import load_invariants
from resolveloop.discovery.recheck import confirm_violation
from resolveloop.discovery.scenarios import propose_scenarios
from resolveloop.events import emit
from resolveloop.github import client as github_client
from resolveloop.models import DiscoveryResult, IncidentEvidence, RunResult, RunStatus
from resolveloop.reporting.postmortem import render_pr_body
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
    # -> VERIFIED: no secondary repair; the first verified patch ships, the defect is reported.
    RunStatus.CONFIRMED_DISCOVERY: {RunStatus.PATCHING, RunStatus.VERIFIED},
}
CATALOG_PATH = "demo_app/contracts/invariants.json"  # inside the pinned checkout


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
        if config.RUN_DISCOVERY:
            result.discoveries = challenge(result, handle)
        manifest = build_manifest(result, baseline["test_hashes"], commands)
        manifest["model_id"] = config.NEBIUS_MODEL_REASONING
        if config.RUN_DISCOVERY:
            manifest["discovery"] = {
                "experimental": True,
                "scenarios_run": len(result.discoveries),
                "confirmed": [d.scenario.scenario_id for d in result.discoveries if _confirmed(d)],
            }
        result.evidence_path = write_evidence_bundle(run_id, manifest)
        emit(run_id, "VERIFIED", "Evidence written", {"evidence_path": result.evidence_path})
        # Read the verified files now: the sandbox (still patched) is destroyed below.
        files = {path: (repo / path).read_text() for path in patch.touched_paths}
        return maybe_create_pr(result, files, manifest)
    except (ModelUnavailable, openai.OpenAIError) as error:
        return _fail(run_id, incident, "MODEL_UNAVAILABLE", f"{type(error).__name__}: {error}")
    except Exception as error:
        return _fail(run_id, incident, "INTERNAL_ERROR", f"{type(error).__name__}: {error}")
    finally:
        if handle is not None:
            destroy_sandbox(handle)


def _confirmed(discovery: DiscoveryResult) -> bool:
    return discovery.violated and discovery.reproduced_twice


def _verdict(discovery: DiscoveryResult) -> str:
    if _confirmed(discovery):
        return "violated, reproduced twice"
    return "violated once, not reproduced" if discovery.violated else "holds"


def challenge(result: RunResult, handle) -> list[DiscoveryResult]:
    """A6 (experimental): challenge the verified patch with trusted catalog scenarios.

    The model only picks catalog IDs and bounded parameters; trusted runner code executes
    them against the patched checkout and a trusted invariant judges each one, twice.
    Discovery can never fail or downgrade the verified core repair: any problem here
    ends as a recorded DISCOVERY_UNCONFIRMED / ORACLE_UNAVAILABLE event, back in VERIFIED.
    """
    run_id = result.run_id
    advance(run_id, RunStatus.CHALLENGING, "Challenging the patch with trusted scenarios")
    try:
        catalog = load_invariants(handle.root / "repo" / CATALOG_PATH)
    except (OSError, ValueError) as error:
        emit(
            run_id,
            "CHALLENGING",
            f"No trusted catalog: {error}",
            {"failure_code": "ORACLE_UNAVAILABLE"},
            "warning",
        )
        advance(run_id, RunStatus.VERIFIED, "Core repair verified; discovery skipped")
        return []
    try:
        specs, rejected = propose_scenarios(
            result.incident, result.patch, catalog, config.MAX_SCENARIOS
        )
    except (ModelUnavailable, openai.OpenAIError) as error:
        specs, rejected = [], [f"{type(error).__name__}: {error}"]
    for reason in rejected:
        emit(run_id, "CHALLENGING", f"Rejected a proposed scenario: {reason}", severity="warning")
    if not specs:
        emit(
            run_id,
            "CHALLENGING",
            "Model proposed no valid catalog scenario",
            {"failure_code": "DISCOVERY_UNCONFIRMED"},
            "warning",
        )
        advance(run_id, RunStatus.VERIFIED, "Core repair verified; no scenario was run")
        return []

    discoveries = []
    for spec in specs:
        label = f"{spec.scenario_id} {spec.params} vs {spec.invariant_id}"
        try:
            found = confirm_violation(handle, spec, catalog, result.patch.base_sha)
        except Exception as error:
            emit(
                run_id,
                "CHALLENGING",
                f"{label}: could not run ({type(error).__name__})",
                {"failure_code": "ORACLE_UNAVAILABLE"},
                "warning",
            )
            continue
        discoveries.append(found)
        emit(
            run_id,
            "CHALLENGING",
            f"{label}: {_verdict(found)}",
            {
                "scenario_id": spec.scenario_id,
                "observed": found.observed,
                "rationale": spec.rationale,
            },
        )

    confirmed = [d for d in discoveries if _confirmed(d)]
    if confirmed:
        ids = ", ".join(d.scenario.scenario_id for d in confirmed)
        advance(
            run_id,
            RunStatus.CONFIRMED_DISCOVERY,
            f"Confirmed a second defect: {ids}",
            {"scenarios": ids},
            "warning",
        )
        advance(
            run_id,
            RunStatus.VERIFIED,
            "Second defect reported, not repaired: the PR carries only the verified incident fix",
        )
    else:
        if any(d.violated for d in discoveries):
            emit(
                run_id,
                "CHALLENGING",
                "A violation did not reproduce; not claimed",
                {"failure_code": "DISCOVERY_UNCONFIRMED"},
                "warning",
            )
        advance(
            run_id,
            RunStatus.VERIFIED,
            f"No confirmed second defect in {len(discoveries)} scenario(s)",
        )
    return discoveries


def _discovery_section(discoveries: list[DiscoveryResult]) -> list[str]:
    if not discoveries:
        return []
    rows = ["| Scenario | Params | Invariant | Observed | Result |", "|---|---|---|---|---|"]
    for d in discoveries:
        outcome = "**confirmed defect, unresolved**" if _confirmed(d) else _verdict(d)
        rows.append(
            f"| `{d.scenario.scenario_id}` | `{json.dumps(d.scenario.params)}` | "
            f"`{d.oracle_id}` | `{json.dumps(d.observed)}` | {outcome} |"
        )
    return [
        "## Additional scenarios (experimental)",
        "Chosen by the model from the human-authored catalog; judged by trusted invariant "
        "code against the patched checkout, each run twice. A confirmed defect is reported "
        "here only: it is not repaired in this PR.",
        "\n".join(rows),
    ]


def _pr_body(result: RunResult, manifest: dict) -> str:
    patch = result.patch
    details = [
        "## Root-cause hypothesis",
        patch.rationale or "No diagnosis was produced.",
        "## Changed paths",
        "\n".join(f"- `{path}`" for path in patch.touched_paths),
        f"Verified on attempt {patch.attempt} of {config.MAX_PATCH_ATTEMPTS}.",
        *_discovery_section(result.discoveries),
        "## Evidence manifest",
        f"<details><summary>{result.run_id}</summary>\n\n```json\n"
        f"{json.dumps(manifest, indent=2, sort_keys=True)}\n```\n</details>",
    ]
    return render_pr_body(result) + "\n\n" + "\n\n".join(details)


def maybe_create_pr(
    result: RunResult, files: dict[str, str] | None = None, manifest: dict | None = None
) -> RunResult:
    """Open a human-review PR, only for a fully verified result. Never merges.

    A GitHub failure leaves the run VERIFIED with its evidence and a GITHUB_ERROR
    event: never a PR_OPENED claim without a PR URL.
    """
    verification = result.verification
    if result.status != RunStatus.VERIFIED or not verification or not result.patch or not files:
        return result
    if not all(
        (
            verification.baseline_red,
            verification.reproducer_green,
            verification.suite_green,
            verification.oracle_intact,
        )
    ):
        return result
    if not config.OPEN_PR_ON_VERIFIED:
        emit(result.run_id, "VERIFIED", "PR step disabled by OPEN_PR_ON_VERIFIED")
        return result

    incident_id = result.incident.incident_id
    try:
        branch = github_client.create_branch(result.patch.base_sha, result.run_id)
        message = f"ResolveLoop: verified repair for incident {incident_id}\n\nRun: {result.run_id}"
        commit_sha = github_client.commit_patch(branch, result.patch.base_sha, files, message)
        url = github_client.open_pull_request(
            branch,
            _pr_body(result, manifest or {}),
            title=f"[ResolveLoop] Verified repair for incident {incident_id}",
        )
    except Exception as error:
        emit(
            result.run_id,
            "VERIFIED",
            f"Verified, but the PR was not opened: {type(error).__name__}: {error}",
            {"failure_code": "GITHUB_ERROR"},
            severity="error",
        )
        return result
    advance(
        result.run_id,
        RunStatus.PR_OPENED,
        f"Opened human-review PR {url}",
        {"pr_url": url, "branch": branch, "commit_sha": commit_sha},
    )
    return result.model_copy(update={"status": RunStatus.PR_OPENED, "pr_url": url})
