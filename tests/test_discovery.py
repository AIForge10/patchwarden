import json

from demo_app.app.store import reset_state
from patchwarden.agent.nebius_client import Reply
from patchwarden.discovery import scenarios
from patchwarden.discovery.catalog import load_invariants, validate_scenario
from patchwarden.discovery.runner import evaluate_invariant, execute_scenario
from patchwarden.models import IncidentEvidence, PatchCandidate, ScenarioSpec


def test_catalog_and_trusted_normal_scenario() -> None:
    catalog = load_invariants("demo_app/contracts/invariants.json")
    spec = ScenarioSpec(
        scenario_id="normal_success",
        invariant_id="success_exactly_one_order",
        params={"amount": 10},
    )
    validate_scenario(spec, catalog)
    reset_state()
    observed = execute_scenario(None, spec)
    assert observed["status"] == "completed"
    assert evaluate_invariant(spec, observed, catalog) is False


def test_model_proposals_are_validated_deduplicated_and_capped(monkeypatch) -> None:
    catalog = load_invariants("demo_app/contracts/invariants.json")
    retry = {"scenario_id": "retry_same_key", "invariant_id": "at_most_one_charge"}
    proposals = [
        retry | {"params": {"attempts": 3}},
        retry | {"params": {"attempts": 3}},  # duplicate
        retry | {"params": {"attempts": 50}},  # out of range
        retry | {"params": {"code": "import os"}},  # unapproved parameter
        {"scenario_id": "normal_success", "invariant_id": "at_most_one_charge"},  # wrong pairing
        {"scenario_id": "normal_success", "invariant_id": "success_exactly_one_order"},
        {"scenario_id": "gateway_decline", "invariant_id": "failed_payment_not_completed"},
    ]
    reply = "Example: [{}]\nAnswer:\n" + json.dumps(proposals)  # the last array is the answer
    monkeypatch.setattr(scenarios, "chat_full", lambda *a, **k: Reply(reply, "stop", False))
    incident = IncidentEvidence(
        incident_id="x",
        repo_url="r",
        commit_sha="a" * 40,
        error_type="ValidationError",
        message="m",
        traceback="t",
        reproducer_id="checkout_malformed_response",
    )
    patch = PatchCandidate(base_sha="a" * 40, unified_diff="--- a/x\n+++ b/x\n")

    accepted, rejected = scenarios.propose_scenarios(incident, patch, catalog, max_count=2)

    assert [(s.scenario_id, s.params) for s in accepted] == [
        ("retry_same_key", {"attempts": 3}),
        ("normal_success", {}),
    ]
    assert len(rejected) == 3
    assert scenarios.propose_scenarios(incident, patch, catalog, max_count=0) == ([], [])
