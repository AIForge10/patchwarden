from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.payments import get_charge_count
from demo_app.app.store import get_order, reset_state


def execute_scenario(handle, spec) -> dict:
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


def evaluate_invariant(spec, observed: dict, catalog: dict) -> bool:
    if spec.scenario_id == "retry_same_key":
        return observed["charge_count"] > 1
    if spec.scenario_id == "gateway_decline":
        return observed["status"] == "completed"
    if spec.scenario_id == "normal_success":
        return observed["status"] != "completed" or not observed["order_exists"]
    raise ValueError("unsupported trusted scenario")
