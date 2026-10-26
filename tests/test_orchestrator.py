"""End-to-end gate tests: real git checkout, real pytest in the sandbox, fake model only."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from resolveloop import config
from resolveloop.agent import patcher
from resolveloop.agent.nebius_client import Reply
from resolveloop.agent.prompts import DIAGNOSIS_SYSTEM
from resolveloop.models import IncidentEvidence, RunStatus
from resolveloop.orchestrator import run_incident
from resolveloop.store import list_events

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


@pytest.fixture
def target(tmp_path, monkeypatch):
    """A pinned git repo holding demo_app, allowlisted, with an isolated DB and evidence dir."""
    repo = tmp_path / "checkout-demo"
    shutil.copytree(
        ROOT / "demo_app",
        repo / "demo_app",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "seed"], check=True)
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)

    # Sandbox commands run `python`; make that this interpreter, with pytest and pydantic.
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(config, "ALLOWED_REPO_URL", str(repo))
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setattr(config, "MAX_PATCH_ATTEMPTS", 3)
    monkeypatch.chdir(tmp_path)  # evidence/ is written relative to the working directory
    return {"repo_url": str(repo), "sha": sha.strip()}


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


def _fake_model(monkeypatch, patch_replies: list[str]) -> list[str]:
    """Diagnosis calls get DIAGNOSIS; patch calls get the next reply. Returns the patch prompts."""
    prompts = []

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
