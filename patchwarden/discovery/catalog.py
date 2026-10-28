import json
from pathlib import Path

_PARAMS = {
    "retry_same_key": {"attempts"},
    "gateway_decline": {"decline_code"},
    "normal_success": {"amount"},
    "malformed_gateway_response": {"payload_variant"},
}


def load_invariants(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get("version") != "1.0" or not isinstance(data.get("invariants"), dict):
        raise ValueError("unsupported invariant catalog")
    return data


def validate_scenario(spec, catalog: dict) -> None:
    invariant = catalog["invariants"].get(spec.invariant_id)
    if not invariant or spec.scenario_id not in invariant["scenario_ids"]:
        raise ValueError("scenario is not approved for invariant")
    allowed = _PARAMS.get(spec.scenario_id)
    if allowed is None or set(spec.params) - allowed:
        raise ValueError("scenario has unapproved parameters")
    if "attempts" in spec.params and spec.params["attempts"] not in (2, 3):
        raise ValueError("attempts must be 2 or 3")
    if "amount" in spec.params and not 1 <= spec.params["amount"] <= 1000:
        raise ValueError("amount out of range")
