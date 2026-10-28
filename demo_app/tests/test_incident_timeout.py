from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.store import reset_state


def test_checkout_gateway_timeout_reproducer() -> None:
    """Known red baseline: a gateway timeout fails the order instead of crashing (demo-005)."""
    reset_state()
    request = CheckoutRequest(
        order_id="slow", amount=20, idempotency_key="slow", provider_mode="timeout"
    )
    assert checkout(request).status == "failed"
