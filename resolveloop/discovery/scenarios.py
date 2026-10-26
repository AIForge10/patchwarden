from resolveloop.models import ScenarioSpec

from .catalog import validate_scenario


def propose_scenarios(incident, patch, catalog: dict, max_count: int) -> list[ScenarioSpec]:
    """Return bounded catalog probes; model output must be validated before use."""
    candidates = [
        ScenarioSpec(
            scenario_id="retry_same_key", invariant_id="at_most_one_charge", params={"attempts": 2}
        ),
        ScenarioSpec(
            scenario_id="gateway_decline",
            invariant_id="failed_payment_not_completed",
            params={"decline_code": "declined"},
        ),
        ScenarioSpec(
            scenario_id="normal_success",
            invariant_id="success_exactly_one_order",
            params={"amount": 10},
        ),
    ]
    accepted = []
    for candidate in candidates[:max_count]:
        validate_scenario(candidate, catalog)
        accepted.append(candidate)
    return accepted
