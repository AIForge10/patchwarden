"""Evidence-gated run coordinator. Owner: Satyabrata.

Runs the gate sequence from plan section 9. Every gate fails closed: when a step
cannot prove its result, the run stops with a failure code instead of claiming success.
"""

import json

import openai

from patchwarden import config
from patchwarden.agent.context import make_unified_diff, paths_from_traceback, read_context
from patchwarden.agent.nebius_client import ModelUnavailable
from patchwarden.agent.patcher import diagnose, propose_patch, repair_until_verified
from patchwarden.agent.research import build_search_query, format_sources, search_error
from patchwarden.discovery.catalog import load_invariants
from patchwarden.discovery.recheck import confirm_violation, run_negative_control
from patchwarden.discovery.scenarios import propose_scenarios
from patchwarden.events import emit
from patchwarden.github import client as github_client
from patchwarden.models import (
    DiscoveryResult,
    IncidentEvidence,
    PatchCandidate,
    RunResult,
    RunStatus,
)
from patchwarden.reporting.postmortem import render_pr_body
from patchwarden.sandbox.e2b_runner import create_sandbox, destroy_sandbox
from patchwarden.sandbox.repository import (
    apply_unified_diff,
    checkout_pinned_repo,
    reset_to_commit,
)
from patchwarden.security import assert_allowed_repo
from patchwarden.store import create_run, get_run, set_run_status
from patchwarden.verifier.baseline import capture_baseline, failure_output, pytest_summary
from patchwarden.verifier.evidence import build_manifest, write_evidence_bundle
from patchwarden.verifier.patch_policy import assert_safe_patch, parse_changed_paths
from patchwarden.verifier.verify import verify_discovery_fix

# FAILED is reachable from any state, so it is not listed.
_ALLOWED = {
    RunStatus.RECEIVED: {RunStatus.BASELINING},
    RunStatus.BASELINING: {RunStatus.DIAGNOSING, RunStatus.UNREPRODUCED},
    RunStatus.DIAGNOSING: {RunStatus.PATCHING},
    RunStatus.PATCHING: {RunStatus.VERIFYING, RunStatus.VERIFIED},
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


def run_incident(incident: IncidentEvidence, repair_discovery: bool | None = None) -> RunResult:
    """Run the gate sequence. repair_discovery overrides REPAIR_DISCOVERY for this run only."""
    repair = config.REPAIR_DISCOVERY if repair_discovery is None else repair_discovery
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
        emit(run_id, "BASELINING", f"Sandbox ready: {handle.backend}", handle.describe())
        checkout_pinned_repo(handle, incident.repo_url, incident.commit_sha)
        try:
            baseline = capture_baseline(handle, incident)
        except ValueError as error:
            if "unknown reproducer" in str(error).lower():
                advance(
                    run_id,
                    RunStatus.UNREPRODUCED,
                    "Unknown reproducer_id; nothing verified to repair",
                    {"reproducer_id": incident.reproducer_id},
                    severity="warning",
                )
                return RunResult(run_id=run_id, status=RunStatus.UNREPRODUCED, incident=incident)
            return _fail(run_id, incident, "INVALID_ALERT", str(error))
        timed_out = (
            baseline["reproducer"]["exit_code"] == 124
            or baseline["original_suite"]["exit_code"] == 124
        )
        if timed_out:
            return _fail(run_id, incident, "SANDBOX_TIMEOUT", "Sandbox command timed out")
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

        # pytest's own tallies from the sandbox, so the timeline shows the tests really ran.
        red = pytest_summary(baseline["reproducer"]["stdout"]) or "failed"
        green = pytest_summary(baseline["original_suite"]["stdout"]) or "passed"
        advance(
            run_id,
            RunStatus.DIAGNOSING,
            f"Baseline red with {incident.error_type} (reproducer: {red}); suite green ({green})",
            {"reproducer": red, "original_suite": green},
        )
        failure = failure_output(baseline)
        repo = handle.root / "repo"
        files = read_context(repo, paths_from_traceback(failure, repo))
        sources: list[dict] = []
        query = build_search_query(incident.error_type, incident.message, failure)
        try:
            sources = search_error(query)
        except Exception as error:
            emit(
                run_id,
                "DIAGNOSING",
                f"Web search skipped ({type(error).__name__}); diagnosis uses the failure only",
                severity="warning",
            )
        diagnosis = diagnose(failure, files, search_results=format_sources(sources))
        if sources:
            emit(
                run_id,
                "DIAGNOSING",
                f"Consulted {len(sources)} untrusted web source(s)",
                {"query": query, "tavily_urls": [item.get("url", "") for item in sources]},
            )
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

        fixed = pytest_summary(outcome.commands["reproducer"].stdout) or "passed"
        suite = pytest_summary(outcome.commands["suite"].stdout) or "passed"
        advance(
            run_id,
            RunStatus.VERIFIED,
            f"Reproducer green ({fixed}), original suite green ({suite}), "
            "protected files unchanged",
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
            result.discoveries = challenge(result, handle, baseline, repair)
        manifest = build_manifest(result, baseline["test_hashes"], commands)
        manifest["model_id"] = config.NEBIUS_MODEL_REASONING
        # Which model wrote each primary attempt; the last one wrote the verified patch.
        manifest["patch_models"] = [config.patch_model(n) for n in range(1, patch.attempt + 1)]
        manifest["patch"] = result.patch.unified_diff  # patch_sha256 is checkable against it
        manifest["incident_id"] = incident.incident_id
        manifest["reproducer_id"] = incident.reproducer_id
        manifest["sandbox"] = handle.describe()
        if sources:
            manifest["tavily_sources"] = [
                {"title": item.get("title", ""), "url": item.get("url", "")} for item in sources
            ]
        if config.RUN_DISCOVERY:
            manifest["discovery"] = {
                "experimental": True,
                "scenarios_run": len(result.discoveries),
                "confirmed": [d.scenario.scenario_id for d in result.discoveries if _confirmed(d)],
                "negative_controls": {
                    d.scenario.scenario_id: d.control_clean
                    for d in result.discoveries
                    if d.control_clean is not None
                },
                "repaired": [d.scenario.scenario_id for d in result.discoveries if d.repaired],
            }
        result.evidence_path = write_evidence_bundle(run_id, manifest)
        emit(run_id, "VERIFIED", "Evidence written", {"evidence_path": result.evidence_path})
        # Read the verified files now: the sandbox (still patched) is destroyed below.
        active_patch = result.patch or patch
        files = {path: (repo / path).read_text() for path in active_patch.touched_paths}
        return maybe_create_pr(result, files, manifest)
    except (ModelUnavailable, openai.OpenAIError) as error:
        return _fail(run_id, incident, "MODEL_UNAVAILABLE", f"{type(error).__name__}: {error}")
    except Exception as error:
        return _fail(run_id, incident, "INTERNAL_ERROR", f"{type(error).__name__}: {error}")
    finally:
        if handle is not None:
            destroy_sandbox(handle)


def _confirmed(discovery: DiscoveryResult) -> bool:
    """Violated twice on the patched checkout, and held on the known-good control."""
    return discovery.violated and discovery.reproduced_twice and discovery.control_clean is True


def _verdict(discovery: DiscoveryResult) -> str:
    if _confirmed(discovery):
        return "violated, reproduced twice, control clean"
    if discovery.reproduced_twice:
        if discovery.control_clean is False:
            return "violated, but also on the known-good control: oracle not trusted"
        return "violated twice, negative control unavailable: not claimed"
    return "violated once, not reproduced" if discovery.violated else "holds"


def _attempt_secondary_repair(
    result: RunResult,
    handle,
    baseline: dict,
    confirmed: list[DiscoveryResult],
) -> None:
    """P2: Optional secondary repair loop for confirmed discovery defects.

    Branch rule: only included in the final PR if the secondary test is red before
    the secondary patch and green afterward, while the original reproducer and full
    suite remain green. Otherwise keep the primary verified patch and report as unresolved.
    """
    run_id = result.run_id
    repo = handle.root / "repo"
    sha = baseline["baseline_sha"]
    primary_patch = result.patch
    if not primary_patch:
        advance(run_id, RunStatus.VERIFIED, "No primary patch; secondary repair skipped")
        return

    target_discovery = confirmed[0]
    spec = target_discovery.scenario
    obs = json.dumps(target_discovery.observed)
    app_files = sorted(
        p.relative_to(repo).as_posix()
        for p in repo.glob("demo_app/app/**/*.py")
        if not p.name.startswith("__")
    )
    hints = "\n".join(f"{p}:1: candidate source file" for p in app_files)
    failure = (
        f"{hints}\n"
        f"Scenario '{spec.scenario_id}' with parameters {json.dumps(spec.params)} "
        f"violated invariant '{spec.invariant_id}'. Observed: {obs}."
    )

    advance(
        run_id,
        RunStatus.PATCHING,
        f"Secondary repair: requesting patch for {spec.scenario_id}",
    )

    feedback = ""
    repaired = False
    for attempt in range(1, config.MAX_PATCH_ATTEMPTS + 1):
        info = {"attempt": attempt, "scenario_id": spec.scenario_id}
        emit(
            run_id,
            "PATCHING",
            f"Secondary repair attempt {attempt} of {config.MAX_PATCH_ATTEMPTS}",
            info,
        )

        # Sandbox has the primary patch applied
        reset_to_commit(handle, sha)
        apply_unified_diff(handle, primary_patch.unified_diff)

        proposal = propose_patch(
            failure,
            repo,
            feedback=feedback,
            attempt=attempt,
            diagnosis=f"Fix invariant violation: {spec.invariant_id}",
            base_sha=sha,
        )
        if not proposal.unified_diff:
            feedback = f"Previous reply was not usable: {proposal.problem}"
            continue

        try:
            assert_safe_patch(proposal.unified_diff, baseline["test_hashes"])
            apply_unified_diff(handle, proposal.unified_diff)
        except (ValueError, RuntimeError) as error:
            feedback = f"Patch rejected by policy: {error}"
            continue

        advance(
            run_id, RunStatus.VERIFYING, f"Verifying secondary patch for {spec.scenario_id}", info
        )
        vr = verify_discovery_fix(handle, baseline, spec)
        if vr.status == "VERIFIED":
            touched = sorted(
                set(primary_patch.touched_paths + parse_changed_paths(proposal.unified_diff))
            )
            # Recompute total combined diff from base_sha to current patched repo
            reset_to_commit(handle, sha)
            clean_files = {p: (repo / p).read_text() for p in touched}
            apply_unified_diff(handle, primary_patch.unified_diff)
            apply_unified_diff(handle, proposal.unified_diff)
            new_files = {p: (repo / p).read_text() for p in touched}

            combined_diff = "".join(
                make_unified_diff(p, clean_files[p], new_files[p])
                for p in touched
                if clean_files[p] != new_files[p]
            )

            result.patch = PatchCandidate(
                base_sha=sha,
                unified_diff=combined_diff,
                rationale=f"{primary_patch.rationale}\nSecondary repair: fixed {spec.invariant_id}",
                attempt=primary_patch.attempt,
                touched_paths=touched,
            )
            result.verification = vr
            target_discovery.repaired = True
            repaired = True
            advance(run_id, RunStatus.VERIFIED, f"Secondary repair verified for {spec.scenario_id}")
            break
        else:
            feedback = f"Secondary fix failed verification: {vr.status}"
            advance(
                run_id,
                RunStatus.PATCHING,
                f"Secondary fix attempt {attempt} failed verification",
                info,
            )

    if not repaired:
        # Fall back to primary verified patch
        reset_to_commit(handle, sha)
        apply_unified_diff(handle, primary_patch.unified_diff)
        advance(
            run_id,
            RunStatus.VERIFIED,
            "Secondary repair did not verify; keeping primary verified fix",
        )


def challenge(
    result: RunResult, handle, baseline: dict | None = None, repair: bool | None = None
) -> list[DiscoveryResult]:
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
        if found.reproduced_twice:
            try:
                found.control_clean = run_negative_control(handle, spec, catalog)
            except Exception as error:
                emit(
                    run_id,
                    "CHALLENGING",
                    f"{label}: negative control could not run ({type(error).__name__})",
                    {"failure_code": "ORACLE_UNAVAILABLE"},
                    "warning",
                )
        discoveries.append(found)
        emit(
            run_id,
            "CHALLENGING",
            f"{label}: {_verdict(found)}",
            {
                "scenario_id": spec.scenario_id,
                "observed": found.observed,
                "control_clean": found.control_clean,
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
        if repair is None:
            repair = config.REPAIR_DISCOVERY
        if repair and baseline is not None:
            _attempt_secondary_repair(result, handle, baseline, confirmed)
        else:
            advance(
                run_id,
                RunStatus.VERIFIED,
                "Second defect reported, not repaired: PR carries only verified incident fix",
            )
    else:
        if any(d.violated for d in discoveries):
            emit(
                run_id,
                "CHALLENGING",
                "A violation did not survive repeat and negative-control checks; not claimed",
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
        if getattr(d, "repaired", False):
            outcome = "**confirmed defect, repaired in this PR**"
        elif _confirmed(d):
            outcome = "**confirmed defect, unresolved**"
        else:
            outcome = _verdict(d)
        rows.append(
            f"| `{d.scenario.scenario_id}` | `{json.dumps(d.scenario.params)}` | "
            f"`{d.oracle_id}` | `{json.dumps(d.observed)}` | {outcome} |"
        )
    return [
        "## Additional scenarios (experimental)",
        "Chosen by the model from the human-authored catalog; judged by trusted invariant "
        "code against the patched checkout, each run twice. A violation is confirmed only if "
        "it reproduces and the same scenario holds on the known-good control gateway.",
        "\n".join(rows),
    ]


def _discovery_risk(discoveries: list[DiscoveryResult]) -> str:
    if any(getattr(d, "repaired", False) for d in discoveries):
        return (
            "- Discovery is experimental. The second fix in this PR was found and verified "
            "by the agent; review it as carefully as the incident fix."
        )
    return "- Discovery is experimental; a confirmed second defect is reported here, not repaired."


def _tavily_section(manifest: dict) -> str:
    sources = manifest.get("tavily_sources") or []
    lines = [
        f"- {item.get('title') or 'Source'}: {item['url']}" for item in sources if item.get("url")
    ]
    return "\n".join(lines) or "None. Diagnosis used the observed failure and source files only."


def _reproducer_section(result: RunResult, manifest: dict) -> str:
    commands = manifest.get("commands") or []
    reproducer = next(
        (item for item in commands if item.get("step") == "baseline_reproducer"), None
    )
    if reproducer and reproducer.get("argv"):
        command = " ".join(str(part) for part in reproducer["argv"])
        return f"Command: `{command}` (exit {reproducer.get('exit_code')})."
    return "See the evidence manifest for the reproducer command and exit code."


def _pr_body(result: RunResult, manifest: dict) -> str:
    patch = result.patch
    details = [
        "## Reproduced failing test",
        _reproducer_section(result, manifest),
        f"Reported error type: `{result.incident.error_type}`.",
        "## Root-cause hypothesis",
        patch.rationale or "No diagnosis was produced.",
        "## Changed paths",
        "\n".join(f"- `{path}`" for path in patch.touched_paths),
        f"Verified on attempt {patch.attempt} of {config.MAX_PATCH_ATTEMPTS}.",
        *_discovery_section(result.discoveries),
        "## Residual risks",
        "- Passing tests are bounded evidence, not mathematical proof.",
        _discovery_risk(result.discoveries),
        "- Seeded demo defects only. PatchWarden never merges or deploys.",
        "## Tavily sources actually consulted",
        _tavily_section(manifest),
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
        emit(
            result.run_id,
            "VERIFIED",
            "PR step disabled on this host (OPEN_PR_ON_VERIFIED=false)",
            {"pr_step": "disabled"},
        )
        return result

    incident_id = result.incident.incident_id
    try:
        branch = github_client.create_branch(result.patch.base_sha, result.run_id)
        message = f"PatchWarden: verified repair for incident {incident_id}\n\nRun: {result.run_id}"
        commit_sha = github_client.commit_patch(branch, result.patch.base_sha, files, message)
        url = github_client.open_pull_request(
            branch,
            _pr_body(result, manifest or {}),
            title=f"[PatchWarden] Verified repair for incident {incident_id}",
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
