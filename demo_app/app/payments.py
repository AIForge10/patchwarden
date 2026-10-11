
from .models import PaymentResult

# Records how many charges were created for each payment key.
_charges: dict[str, int] = {}


def charge(
    amount: int,
    idempotency_key: str,
    mode: str = "normal",
) -> PaymentResult | dict | None:
    """Simulate a payment provider without real transactions."""

    if mode == "timeout":
        raise TimeoutError("Payment gateway timed out")

    if mode == "malformed":
        return None

    if mode == "decline":
        return {"status": "failed"}

    # BUG 2: Every retry creates another charge.
    # The same idempotency key should only be charged once.
    _charges[idempotency_key] = (
        _charges.get(idempotency_key, 0) + 1
    )

    return {
    "status": "success",
    "transaction_id": f"txn-{idempotency_key}",
}


def get_charge_count(idempotency_key: str) -> int:
    """Return how many times this payment was charged."""
    return _charges.get(idempotency_key, 0)


def reset_charges() -> None:
    """Clear fake payment records between tests."""
    _charges.clear()
