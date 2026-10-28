from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.store import reset_state


def test_checkout_unapproved_payment_reproducer() -> None:
    """Known red baseline: a payment held for review is not approved (incident demo-003)."""
    reset_state()
    request = CheckoutRequest(
        order_id="held", amount=40, idempotency_key="held", provider_mode="review"
    )
    order = checkout(request)
    assert order.status != "completed", "an unapproved payment completed the order"
