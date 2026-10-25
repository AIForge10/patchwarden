from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    order_id: str
    amount: int = Field(gt=0, le=1000)
    idempotency_key: str
    provider_mode: str = "normal"


class Order(BaseModel):
    order_id: str
    status: str
    charge_id: str | None = None


class PaymentResult(BaseModel):
    status: str
    charge_id: str | None = None
