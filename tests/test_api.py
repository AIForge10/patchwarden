import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from resolveloop import config
from resolveloop.api import webhooks
from resolveloop.api.main import create_app
from resolveloop.events import emit
from resolveloop.models import IncidentEvidence, RunStatus
from resolveloop.store import create_run, set_run_status


def test_signed_webhook_is_accepted_and_deduplicated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(config, "ALLOWED_REPO_URL", "https://github.com/acme/checkout")
    started = []
    monkeypatch.setattr(webhooks, "run_incident", lambda incident: started.append(incident))
    payload = {
        "incident_id": "api-incident",
        "repo_url": "https://github.com/acme/checkout",
        "commit_sha": "a" * 40,
        "error_type": "ValidationError",
        "message": "bad payment payload",
        "traceback": "Traceback",
        "reproducer_id": "checkout_malformed_response",
        "timestamp": "2026-10-25T12:00:00Z",
    }
    body = json.dumps(payload).encode()
    signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    client = TestClient(create_app())
    headers = {"X-ResolveLoop-Signature": f"sha256={signature}"}
    first = client.post("/webhooks/incident", content=body, headers=headers)
    second = client.post("/webhooks/incident", content=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert [incident.incident_id for incident in started] == ["api-incident"]  # started once
    assert client.post("/webhooks/incident", content=body).status_code == 401
    assert len(started) == 1


def test_run_status_shows_pr_and_evidence_from_the_event_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.chdir(tmp_path)
    incident = IncidentEvidence(
        incident_id="ui-incident",
        repo_url="https://github.com/acme/checkout",
        commit_sha="a" * 40,
        error_type="ValidationError",
        message="bad payment payload",
        traceback="Traceback",
        reproducer_id="checkout_malformed_response",
    )
    run_id = create_run(incident)
    client = TestClient(create_app())
    assert client.get(f"/runs/{run_id}/evidence").status_code == 404  # nothing verified yet

    (tmp_path / "evidence").mkdir()
    evidence = tmp_path / "evidence" / f"{run_id}.json"
    evidence.write_text(json.dumps({"run_id": run_id, "patch_sha256": "f" * 64}))
    set_run_status(run_id, RunStatus.VERIFIED)
    emit(run_id, "VERIFIED", "Evidence written", {"evidence_path": f"evidence/{run_id}.json"})
    url = "https://github.com/acme/checkout/pull/7"
    emit(run_id, "VERIFIED", "would-be PR", {"pr_url": url})
    assert client.get(f"/runs/{run_id}").json()["pr_url"] is None  # not PR_OPENED yet

    set_run_status(run_id, RunStatus.PR_OPENED)
    status = client.get(f"/runs/{run_id}").json()
    assert status["pr_url"] == url and status["evidence_path"] == f"evidence/{run_id}.json"
    assert client.get(f"/runs/{run_id}/evidence").json()["patch_sha256"] == "f" * 64
    assert client.get("/runs").json()[0]["run_id"] == run_id
    assert client.get("/").url.path == "/ui/"


def test_recorded_run_replays_the_stored_event_log(tmp_path, monkeypatch) -> None:
    from resolveloop.scripts.record_run import record

    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    incident = IncidentEvidence(
        incident_id="rec-incident",
        repo_url="https://github.com/acme/checkout",
        commit_sha="a" * 40,
        error_type="ValidationError",
        message="bad payment payload",
        traceback="Traceback",
        reproducer_id="checkout_malformed_response",
    )
    run_id = create_run(incident)
    set_run_status(run_id, RunStatus.FAILED)
    emit(run_id, "FAILED", "No patch verified", {"failure_code": "VERIFY_FAILED"}, "error")

    path = record(run_id, tmp_path / "recordings")
    recording = json.loads(path.read_text())
    assert recording["run"]["status"] == "FAILED" and recording["run"]["pr_url"] is None
    assert [e["message"] for e in recording["events"]] == ["No patch verified"]
    index = json.loads((tmp_path / "recordings" / "index.json").read_text())
    assert index == [
        {"run_id": run_id, "incident_id": "rec-incident", "file": path.name, "status": "FAILED"}
    ]
