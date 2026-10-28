"""Trusted scenario runner: fixed Python per scenario ID, never model-written code.

With a sandbox handle, the scenario runs in a subprocess whose working directory is the
sandbox checkout, so it exercises the patched code under test (this module comes from the
installed patchwarden package, outside the patchable tree). Without one, it runs in process.
"""

import json
import sys

from patchwarden.models import ScenarioSpec


def _execute_local(spec, control: bool = False) -> dict:
    # Imported here: under the sandbox subprocess these resolve to the checkout's demo_app.
    from demo_app.app import main
    from demo_app.app.payments import get_charge_count

    if not control:
        return _run_scenario(spec, main.checkout, get_charge_count)
    # Negative control: the same checkout flow against the known-good gateway, which the
    # patch policy keeps out of reach. A sound oracle must hold here.
    from demo_app.seed_variants.control import payments as gateway

    seeded = main.charge
    gateway.reset_charges()
    main.charge = gateway.charge
    try:
        return _run_scenario(spec, main.checkout, gateway.get_charge_count)
    finally:
        main.charge = seeded


def _run_scenario(spec, checkout, get_charge_count) -> dict:
    from demo_app.app.models import CheckoutRequest
    from demo_app.app.store import get_order, reset_state

    reset_state()
    if spec.scenario_id == "retry_same_key":
        key = "scenario-retry"
        for index in range(spec.params.get("attempts", 2)):
            checkout(CheckoutRequest(order_id=f"retry-{index}", amount=10, idempotency_key=key))
        return {"charge_count": get_charge_count(key)}
    if spec.scenario_id == "gateway_decline":
        order = checkout(
            CheckoutRequest(
                order_id="declined", amount=10, idempotency_key="declined", provider_mode="decline"
            )
        )
        return {"status": order.status}
    if spec.scenario_id == "normal_success":
        order = checkout(
            CheckoutRequest(
                order_id="success", amount=spec.params.get("amount", 10), idempotency_key="success"
            )
        )
        return {"status": order.status, "order_exists": get_order("success") is not None}
    raise ValueError("unsupported trusted scenario")


def execute_scenario(handle, spec, control: bool = False) -> dict:
    if handle is None:
        return _execute_local(spec, control)
    from patchwarden.sandbox.e2b_runner import exec_fixed

    argv = ["python", "-m", "patchwarden.discovery.runner", spec.model_dump_json()]
    if control:
        argv.append("--control")
    result = exec_fixed(handle, argv, "repo", timeout_s=60)
    lines = result.stdout.strip().splitlines()
    if result.exit_code != 0 or not lines:
        raise RuntimeError(f"scenario {spec.scenario_id} did not run: {result.stdout[-500:]}")
    return json.loads(lines[-1])


def evaluate_invariant(spec, observed: dict, catalog: dict) -> bool:
    if spec.scenario_id == "retry_same_key":
        return observed["charge_count"] > 1
    if spec.scenario_id == "gateway_decline":
        return observed["status"] == "completed"
    if spec.scenario_id == "normal_success":
        return observed["status"] != "completed" or not observed["order_exists"]
    raise ValueError("unsupported trusted scenario")


if __name__ == "__main__":
    spec = ScenarioSpec.model_validate_json(sys.argv[1])
    print(json.dumps(_execute_local(spec, control="--control" in sys.argv[2:])))
