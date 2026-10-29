"""Public live-demo endpoint: bundled alerts only, capped, E2B-only, PRs only by opt-in."""

import pytest
from fastapi.testclient import TestClient

from patchwarden import config
from patchwarden.api import demo
from patchwarden.api.main import create_app
from patchwarden.store import list_events


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(config, "ALLOWED_REPO_URL", "https://github.com/Satyabratadas/patchwarden-demo")
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "dummy-key")  # pragma: allowlist secret
    monkeypatch.setattr(config, "NEBIUS_MODEL_REASONING", "nvidia/ok")
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", False)
    monkeypatch.setattr(config, "PUBLIC_DEMO_RUNS_PER_DAY", 2)
    monkeypatch.setattr(demo, "use_e2b", lambda: True)
    demo.reset()
    started = []

    def fake_run(incident, repair_discovery):
        started.append((incident, repair_discovery))

    monkeypatch.setattr(demo, "run_incident", fake_run)
    with TestClient(create_app()) as test_client:
        test_client.started = started
        yield test_client
    demo.reset()


def test_lists_the_six_bundled_cases(client) -> None:
    body = client.get("/demo").json()
    assert body["enabled"] and body["remaining_today"] == 2 and body["busy_run"] is None
    assert [case["case"] for case in body["cases"]] == ["01", "02", "03", "04", "05", "06"]
    assert body["cases"][1]["repair_discovery"] is True


def test_starts_a_run_from_the_bundled_alert_only(client) -> None:
    response = client.post("/demo/runs", json={"case": "04", "repo_url": "https://evil.example"})
    assert response.status_code == 202
    (incident, repair), = client.started
    assert incident.repo_url == "https://github.com/Satyabratadas/patchwarden-demo"
    assert incident.reproducer_id == "checkout_unknown_sku" and repair is False
    assert incident.incident_id.startswith("demo-004-live-")
    events = list_events(response.json()["run_id"])
    assert [e.message for e in events] == ["Live demo alert accepted"]


def test_case_02_turns_on_the_second_repair_for_that_run_only(client) -> None:
    assert client.post("/demo/runs", json={"case": "02"}).status_code == 202
    assert client.started[0][1] is True and config.REPAIR_DISCOVERY is False


def test_unknown_case_is_rejected(client) -> None:
    assert client.post("/demo/runs", json={"case": "../../etc/passwd"}).status_code == 404
    assert client.started == []


def test_one_live_run_at_a_time_and_a_daily_cap(client, monkeypatch) -> None:
    monkeypatch.setattr(demo, "_run", lambda incident, repair: None)  # leaves the run active
    first = client.post("/demo/runs", json={"case": "01"})
    busy = client.post("/demo/runs", json={"case": "03"})
    assert busy.status_code == 409 and busy.headers["X-Run-Id"] == first.json()["run_id"]
    demo._state["active"] = None
    assert client.post("/demo/runs", json={"case": "03"}).status_code == 202
    demo._state["active"] = None
    assert client.post("/demo/runs", json={"case": "05"}).status_code == 429


@pytest.mark.parametrize(
    ("setting", "value"),
    [("PUBLIC_DEMO_RUNS_PER_DAY", 0), ("OPEN_PR_ON_VERIFIED", True), ("NEBIUS_API_KEY", "")],
)
def test_refuses_unless_safe_to_run(client, monkeypatch, setting, value) -> None:
    monkeypatch.setattr(config, setting, value)
    response = client.post("/demo/runs", json={"case": "01"})
    assert response.status_code == 403 and client.started == []
    assert client.get("/demo").json()["enabled"] is False


def test_refuses_without_e2b(client, monkeypatch) -> None:
    monkeypatch.setattr(demo, "use_e2b", lambda: False)
    response = client.post("/demo/runs", json={"case": "01"})
    assert response.status_code == 403 and "E2B" in response.json()["detail"]


def test_missing_fixtures_disable_the_demo(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(demo, "FIXTURES", tmp_path / "absent")
    body = client.get("/demo").json()
    assert body["enabled"] is False and "missing" in body["reason"]
    assert client.post("/demo/runs", json={"case": "01"}).status_code == 403


def test_public_prs_need_the_opt_in_and_a_github_target(client, monkeypatch) -> None:
    assert client.get("/demo").json()["opens_prs"] is False
    monkeypatch.setattr(config, "OPEN_PR_ON_VERIFIED", True)
    monkeypatch.setattr(config, "PUBLIC_DEMO_OPEN_PRS", True)
    monkeypatch.setattr(config, "GITHUB_TOKEN", "")
    body = client.get("/demo").json()
    assert body["enabled"] is False and "GitHub is not configured" in body["reason"]
    monkeypatch.setattr(config, "GITHUB_TOKEN", "demo-token")  # pragma: allowlist secret
    monkeypatch.setattr(config, "GITHUB_OWNER", "Satyabratadas")
    monkeypatch.setattr(config, "GITHUB_TARGET_REPO", "patchwarden-demo")
    body = client.get("/demo").json()
    assert body["enabled"] and body["opens_prs"]
    assert body["pr_repo"] == "https://github.com/Satyabratadas/patchwarden-demo"
    assert client.post("/demo/runs", json={"case": "01"}).status_code == 202
