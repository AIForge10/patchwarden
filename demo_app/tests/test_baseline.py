
import pytest
from fastapi.testclient import TestClient

from demo_app.app.main import app
from demo_app.app.store import get_order_count, reset_state

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_state()
    yield
    reset_state()


def test_success_creates_one_order():
    response = client.post(
        "/checkout",
        json={
            "order_id": "order-1",
            "amount": 50,
            "idempotency_key": "key-1",
            "mode": "normal",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert get_order_count() == 1


def test_failed_payment_not_completed():
    response = client.post(
        "/checkout",
        json={
            "order_id": "order-2",
            "amount": 50,
            "idempotency_key": "key-2",
            "mode": "decline",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_valid_request_returns_response():
    response = client.post(
        "/checkout",
        json={
            "order_id": "order-3",
            "amount": 100,
            "idempotency_key": "key-3",
        },
    )

    assert response.status_code == 200
    assert response.json()["order_id"] == "order-3"
