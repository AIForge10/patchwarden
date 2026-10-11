
from fastapi.testclient import TestClient

from demo_app.app.main import app
from demo_app.app.store import reset_state

client = TestClient(app)


def test_checkout_malformed_response_reproducer():
    reset_state()

    response = client.post(
        "/checkout",
        json={
            "order_id": "order-crash",
            "amount": 50,
            "idempotency_key": "key-crash",
            "mode": "malformed",
        },
    )

    assert response.status_code == 502
