from .models import PaymentResult

_charges: dict[str, int] = {}


def charge(amount: int, idempotency_key: str, mode: str) -> PaymentResult | dict[str, str]:
    if mode == "decline":
        return PaymentResult(status="declined")
    if mode == "review":
        return PaymentResult(status="review")
    if mode == "timeout":
        raise TimeoutError("gateway timed out")
    if mode == "malformed":
        return {"unexpected": "gateway payload"}
    if mode != "normal":
        raise ValueError("unsupported provider mode")
    _charges[idempotency_key] = _charges.get(idempotency_key, 0) + 1
    return PaymentResult(status="approved", charge_id=f"ch_{idempotency_key}")


def get_charge_count(key: str) -> int:
    return _charges.get(key, 0)


def reset_charges() -> None:
    _charges.clear()
