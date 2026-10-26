from resolveloop import config
from resolveloop.models import IncidentEvidence, RunStatus
from resolveloop.orchestrator import run_incident


def test_orchestrator_fails_closed_without_sandbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    incident = IncidentEvidence(
        incident_id="orchestrator-1",
        repo_url="https://github.com/acme/checkout",
        commit_sha="a" * 40,
        error_type="ValidationError",
        message="bad response",
        traceback="Traceback",
        reproducer_id="checkout_malformed_response",
    )
    result = run_incident(incident)
    assert result.status == RunStatus.UNREPRODUCED
