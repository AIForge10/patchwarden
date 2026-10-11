
from typing import Literal

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    order_id: str
    amount: int = Field(gt=0)
    idempotency_key: str
    mode: Literal["normal", "malformed", "timeout", "retry", "decline"] = "normal"


class PaymentResult(BaseModel):
    status: Literal["success", "failed"]
    transaction_id: str | None = None


class Order(BaseModel):
    order_id: str
    status: Literal["completed", "failed"]


class CheckoutResponse(BaseModel):
    order_id: str
    status: Literal["completed", "failed"]
