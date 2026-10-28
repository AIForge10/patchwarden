"""Known-good fake gateway isolated from the seeded incident implementation."""

from demo_app.app.models import PaymentResult

_charges: dict[str, int] = {}


def charge(amount: int, idempotency_key: str, mode: str = "normal") -> PaymentResult | None:
    if amount <= 0:
        raise ValueError("amount must be positive")
    if mode == "timeout":
        raise TimeoutError("gateway timed out")
    if mode == "malformed":
        return None
    if mode == "decline":
        return PaymentResult(status="declined")
    if mode == "review":
        return PaymentResult(status="review")
    if mode != "normal":
        raise ValueError("unsupported provider mode")
    _charges.setdefault(idempotency_key, 1)
    return PaymentResult(status="approved", charge_id=f"ch_{idempotency_key}")


def get_charge_count(idempotency_key: str) -> int:
    return _charges.get(idempotency_key, 0)


def reset_charges() -> None:
    _charges.clear()
