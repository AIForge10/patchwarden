
"""Known-good payment gateway for negative-control tests."""

from demo_app.app.models import PaymentResult

_charges: dict[str, int] = {}


def charge(
    amount: int,
    idempotency_key: str,
    mode: str = "normal",
) -> PaymentResult | None:
    if mode == "timeout":
        raise TimeoutError("Payment gateway timed out")

    if mode == "malformed":
        return None

    if mode == "decline":
        return PaymentResult(status="failed")

    # Correct: retries do not create duplicate charges.
    if idempotency_key not in _charges:
        _charges[idempotency_key] = 1

    return PaymentResult(
        status="success",
        transaction_id=f"txn-{idempotency_key}",
    )


def get_charge_count(idempotency_key: str) -> int:
    return _charges.get(idempotency_key, 0)


def reset_charges() -> None:
    _charges.clear()
