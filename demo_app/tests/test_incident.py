from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.store import reset_state


def test_checkout_malformed_response_reproducer() -> None:
    """Known red baseline: run this test only to reproduce incident demo-001."""
    reset_state()
    request = CheckoutRequest(
        order_id="bad", amount=50, idempotency_key="bad", provider_mode="malformed"
    )
    assert checkout(request).status == "failed"
