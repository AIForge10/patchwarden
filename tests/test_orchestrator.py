"""End-to-end gate tests: real git checkout, real pytest in the sandbox, fake model only."""

import json
import subprocess
from pathlib import Path

from resolveloop import config
from resolveloop.agent import patcher
from resolveloop.agent.nebius_client import Reply
from resolveloop.agent.prompts import DIAGNOSIS_SYSTEM
from resolveloop.discovery import scenarios
from resolveloop.models import CommandResult, IncidentEvidence, RunStatus
from resolveloop.orchestrator import run_incident
from resolveloop.store import list_events
from resolveloop.verifier import baseline as baseline_mod

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "demo_app/app/main.py").read_text()
BUG = "    result = PaymentResult.model_validate(response)\n"
FIX = MAIN.replace(
    BUG,
    "    if not isinstance(response, PaymentResult):\n"
    '        return create_order(request.order_id, "failed")\n'
    "    result = response\n",
)
# Reproducer goes green, but every order now fails: the original suite must catch it.
REGRESSION = MAIN.replace(BUG, '    return create_order(request.order_id, "failed")\n')
DIAGNOSIS = (
    "EVIDENCE: demo_app/app/main.py:14 - validates an unchecked gateway payload\n"
    "HYPOTHESIS: malformed gateway response raises ValidationError\n"
    "UNCERTAINTY: low - trace is direct"
)


def _file_reply(path: str, code: str) -> str:
    return f"FILE: {path}\n```python\n{code}```\n"


def _commit_variant(target, path: str, old: str, new: str) -> str:
    """Seed a disclosed defect on top of the target repo; returns the new pinned SHA."""
    file = Path(target["repo_url"]) / path
    source = file.read_text()
    assert old in source
    file.write_text(source.replace(old, new))
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C"]
    subprocess.run([*git, target["repo_url"], "commit", "-qam", "variant"], check=True)
    sha = subprocess.check_output(["git", "-C", target["repo_url"], "rev-parse", "HEAD"], text=True)
    return sha.strip()


def _incident(target, **overrides) -> IncidentEvidence:
    fields = {
        "incident_id": "demo-001",
        "repo_url": target["repo_url"],
        "commit_sha": target["sha"],
        "error_type": "ValidationError",
        "message": "Unexpected payment response",
        "traceback": "Traceback (most recent call last): ...",
        "reproducer_id": "checkout_malformed_response",
    } | overrides
    return IncidentEvidence(**fields)


SCENARIOS = [
    {
        "scenario_id": "retry_same_key",
        "invariant_id": "at_most_one_charge",
        "params": {"attempts": 2},
    },
    {
        "scenario_id": "gateway_decline",
        "invariant_id": "failed_payment_not_completed",
        "params": {"decline_code": "declined"},
    },
    {
        "scenario_id": "normal_success",
        "invariant_id": "success_exactly_one_order",
        "params": {"amount": 10},
    },
    {"scenario_id": "drop_database", "invariant_id": "at_most_one_charge", "params": {}},
]


def _fake_model(monkeypatch, patch_replies: list[str], scenario_reply: str = "") -> list[str]:
    """Diagnosis calls get DIAGNOSIS; patch calls get the next reply. Returns the patch prompts."""
    prompts = []
    monkeypatch.setattr(
        scenarios, "chat_full", lambda *args, **kwargs: Reply(scenario_reply, "stop", False)
    )

    def chat_full(prompt, system="", model="", max_tokens=0, use_cache=True):
        if system == DIAGNOSIS_SYSTEM:
            return Reply(DIAGNOSIS, "stop", False)
        prompts.append(prompt)
        return Reply(patch_replies[len(prompts) - 1], "stop", False)

    monkeypatch.setattr(patcher, "chat_full", chat_full)
    return prompts


def _failure_codes(run_id: str) -> list[str]:
    return [e.metadata["failure_code"] for e in list_events(run_id) if "failure_code" in e.metadata]


def test_regression_is_rejected_then_real_fix_verified(target, monkeypatch) -> None:
    prompts = _fake_model(
        monkeypatch,
        [_file_reply("demo_app/app/main.py", REGRESSION), _file_reply("demo_app/app/main.py", FIX)],
    )
    result = run_incident(_incident(target))

    assert result.status == RunStatus.VERIFIED
    assert result.patch.attempt == 2 and result.patch.touched_paths == ["demo_app/app/main.py"]
    assert result.verification.reproducer_green and result.verification.suite_green
    assert result.verification.oracle_intact
    assert "original test suite now fails" in prompts[1]  # verifier output fed back
    assert "demo_app/app/main.py:14" in prompts[0]  # model saw the observed red reproducer
    assert Path(result.evidence_path).is_file()
    stages = [e.stage for e in list_events(result.run_id)]
    assert stages[:2] == ["BASELINING", "DIAGNOSING"] and stages[-2:] == ["VERIFIED", "VERIFIED"]


def test_every_attempt_failing_ends_failed_not_verified(target, monkeypatch) -> None:
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", REGRESSION)] * 3)
    result = run_incident(_incident(target))

    assert result.status == RunStatus.FAILED
    assert result.verification.status == "VERIFY_FAILED" and not result.verification.suite_green
    assert _failure_codes(result.run_id) == ["VERIFY_FAILED"]


def test_model_cannot_touch_tests(target, monkeypatch) -> None:
    gutted = "def test_checkout_malformed_response_reproducer():\n    pass\n"
    _fake_model(monkeypatch, [_file_reply("demo_app/tests/test_incident.py", gutted)] * 3)
    result = run_incident(_incident(target))

    assert result.status == RunStatus.FAILED  # test files are never offered or applied
    assert _failure_codes(result.run_id) == ["VERIFY_FAILED"]


def test_wrong_failure_reason_is_unreproduced(target, monkeypatch) -> None:
    prompts = _fake_model(monkeypatch, [])
    result = run_incident(_incident(target, error_type="KeyError"))

    assert result.status == RunStatus.UNREPRODUCED
    assert prompts == []  # no model call without a red baseline


def test_duplicate_alert_does_not_rerun(target, monkeypatch) -> None:
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)])
    first = run_incident(_incident(target))
    second = run_incident(_incident(target))

    assert second.run_id == first.run_id and second.status == RunStatus.VERIFIED
    assert len(list_events(first.run_id)) == len(list_events(second.run_id))


def test_unallowlisted_repo_fails_closed(target, monkeypatch) -> None:
    prompts = _fake_model(monkeypatch, [])
    result = run_incident(_incident(target, repo_url="https://github.com/acme/checkout"))

    assert result.status == RunStatus.FAILED and prompts == []
    assert _failure_codes(result.run_id) == ["UNAUTHORIZED_REPO"]


def test_verified_run_opens_pr_with_exactly_the_verified_code(
    target, monkeypatch, fake_github
) -> None:
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", True)
    fake_github.base_sha = target["sha"]
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)])
    result = run_incident(_incident(target))

    assert result.status == RunStatus.PR_OPENED
    assert result.pr_url == fake_github.pulls[0].html_url
    (commit,) = fake_github.commits.values()
    assert commit["parents"] == [target["sha"]]
    assert commit["files"] == {"demo_app/app/main.py": ("100644", FIX)}
    pull = fake_github.pulls[0]
    assert pull.title == "[ResolveLoop] Verified repair for incident demo-001"
    assert "HYPOTHESIS: malformed gateway response" in pull.body
    assert '"patch_sha256"' in pull.body  # evidence manifest embedded for reviewers
    assert "## Residual risks" in pull.body
    assert "## Tavily sources actually consulted" in pull.body
    assert "Diagnosis used the observed failure and source files only" in pull.body
    events = list_events(result.run_id)
    assert events[-1].stage == "PR_OPENED" and events[-1].metadata["pr_url"] == result.pr_url


def test_github_error_keeps_verified_and_claims_no_pr(target, monkeypatch, fake_github) -> None:
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", True)
    fake_github.base_sha = target["sha"]
    fake_github.fail_on = "create_pull"
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)])
    result = run_incident(_incident(target))

    assert result.status == RunStatus.VERIFIED and result.pr_url is None
    assert Path(result.evidence_path).is_file()  # verified evidence is preserved
    assert _failure_codes(result.run_id) == ["GITHUB_ERROR"]
    assert "PR_OPENED" not in [e.stage for e in list_events(result.run_id)]


def test_discovery_challenges_the_patch_and_rejects_invented_scenarios(target, monkeypatch) -> None:
    monkeypatch.setattr(config, "RUN_DISCOVERY", True)
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)], json.dumps(SCENARIOS))
    result = run_incident(_incident(target))

    assert result.status == RunStatus.VERIFIED
    assert [d.scenario.scenario_id for d in result.discoveries] == [
        "retry_same_key",
        "gateway_decline",
        "normal_success",
    ]  # the invented scenario never ran
    assert not any(d.violated for d in result.discoveries)
    stages = [e.stage for e in list_events(result.run_id)]
    assert "CHALLENGING" in stages and "CONFIRMED_DISCOVERY" not in stages
    messages = [e.message for e in list_events(result.run_id)]
    assert any("Rejected a proposed scenario: drop_database" in m for m in messages)
    manifest = json.loads(Path(result.evidence_path).read_text())
    assert manifest["discovery"] == {"experimental": True, "scenarios_run": 3, "confirmed": []}


def test_confirmed_second_defect_is_reported_not_repaired(target, monkeypatch, fake_github) -> None:
    sha = _commit_variant(
        target,
        "demo_app/app/payments.py",
        "    if idempotency_key not in _charges:\n        _charges[idempotency_key] = 1\n",
        "    _charges[idempotency_key] = _charges.get(idempotency_key, 0) + 1\n",
    )
    monkeypatch.setattr(config, "RUN_DISCOVERY", True)
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", True)
    fake_github.base_sha = sha
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)], json.dumps(SCENARIOS))
    result = run_incident(_incident(target, commit_sha=sha))

    assert result.status == RunStatus.PR_OPENED
    (retry,) = [d for d in result.discoveries if d.violated]
    assert retry.scenario.scenario_id == "retry_same_key" and retry.reproduced_twice
    assert retry.observed == {"charge_count": 2}  # ran against the checkout, not this repo
    stages = [e.stage for e in list_events(result.run_id)]
    assert stages.index("CONFIRMED_DISCOVERY") < stages.index("PR_OPENED")
    (commit,) = fake_github.commits.values()
    assert list(commit["files"]) == ["demo_app/app/main.py"]  # only the verified fix ships
    assert "**confirmed defect, unresolved**" in fake_github.pulls[0].body


def test_unusable_scenario_reply_keeps_the_verified_repair(target, monkeypatch) -> None:
    monkeypatch.setattr(config, "RUN_DISCOVERY", True)
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)], "I cannot help.")
    result = run_incident(_incident(target))

    assert result.status == RunStatus.VERIFIED and result.discoveries == []
    assert _failure_codes(result.run_id) == ["DISCOVERY_UNCONFIRMED"]


def test_unknown_reproducer_is_unreproduced_not_verified(target, monkeypatch) -> None:
    prompts = _fake_model(monkeypatch, [])
    result = run_incident(_incident(target, reproducer_id="not_a_known_test"))

    assert result.status == RunStatus.UNREPRODUCED and prompts == []
    assert result.pr_url is None


def test_sandbox_timeout_fails_closed_and_destroys_the_sandbox(target, monkeypatch) -> None:
    prompts = _fake_model(monkeypatch, [])
    timed_out = CommandResult(argv=["pytest"], exit_code=124, stdout="timeout", duration_ms=1)

    def boom(handle, reproducer_id):
        return timed_out

    monkeypatch.setattr(baseline_mod, "run_reproducer", boom)
    monkeypatch.setattr(
        baseline_mod,
        "run_regression_suite",
        lambda handle: CommandResult(argv=["pytest"], exit_code=0, stdout="", duration_ms=1),
    )
    result = run_incident(_incident(target))

    assert result.status == RunStatus.FAILED and prompts == []
    assert _failure_codes(result.run_id) == ["SANDBOX_TIMEOUT"]


def test_tavily_sources_reach_diagnosis_and_the_pr(target, monkeypatch, fake_github) -> None:
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", True)
    fake_github.base_sha = target["sha"]
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)])
    monkeypatch.setattr(
        "resolveloop.orchestrator.search_error",
        lambda query: [{"title": "Pydantic validation", "url": "https://docs.pydantic.dev/errors"}],
    )
    result = run_incident(_incident(target))

    assert result.status == RunStatus.PR_OPENED
    body = fake_github.pulls[0].body
    assert "https://docs.pydantic.dev/errors" in body
    sources = json.loads(Path(result.evidence_path).read_text())["tavily_sources"]
    assert sources[0]["url"].startswith("https://")


def test_tavily_failure_does_not_block_a_verified_repair(target, monkeypatch) -> None:
    def boom(query):
        raise RuntimeError("tavily down")

    monkeypatch.setattr("resolveloop.orchestrator.search_error", boom)
    _fake_model(monkeypatch, [_file_reply("demo_app/app/main.py", FIX)])
    result = run_incident(_incident(target))

    assert result.status == RunStatus.VERIFIED
    assert any("Web search skipped" in event.message for event in list_events(result.run_id))
