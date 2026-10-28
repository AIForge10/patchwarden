from demo_app.app.main import checkout
from demo_app.app.models import CheckoutRequest
from demo_app.app.payments import get_charge_count
from demo_app.app.store import reset_state


def test_checkout_unknown_sku_reproducer() -> None:
    """Known red baseline: an unknown SKU fails the order without charging (incident demo-004)."""
    reset_state()
    request = CheckoutRequest(
        order_id="retired", amount=30, idempotency_key="retired", sku="sku-retired"
    )
    order = checkout(request)
    assert order.status == "failed"
    assert get_charge_count("retired") == 0
