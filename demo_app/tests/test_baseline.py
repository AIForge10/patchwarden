from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.store import reset_state


def setup_function() -> None:
    reset_state()


def test_success_creates_one_order() -> None:
    order = checkout(CheckoutRequest(order_id="one", amount=25, idempotency_key="one"))
    assert order.status == "completed" and order.charge_id == "ch_one"


def test_failed_payment_not_completed() -> None:
    order = checkout(
        CheckoutRequest(
            order_id="declined", amount=25, idempotency_key="declined", provider_mode="decline"
        )
    )
    assert order.status == "failed"


def test_valid_request_returns_response() -> None:
    assert (
        checkout(CheckoutRequest(order_id="two", amount=1, idempotency_key="two")).order_id == "two"
    )
