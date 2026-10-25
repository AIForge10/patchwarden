from demo_app.app.store import reset_state
from resolveloop.discovery.catalog import load_invariants, validate_scenario
from resolveloop.discovery.runner import evaluate_invariant, execute_scenario
from resolveloop.models import ScenarioSpec


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
