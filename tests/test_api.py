import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from resolveloop import config
from resolveloop.api.main import create_app


def test_signed_webhook_is_accepted_and_deduplicated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(config, "ALLOWED_REPO_URL", "https://github.com/acme/checkout")
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
    assert client.post("/webhooks/incident", content=body).status_code == 401
