from fastapi import FastAPI, HTTPException

from .models import CheckoutRequest, Order, PaymentResult
from .payments import charge
from .store import create_order, get_order, reserve_item

app = FastAPI(title="checkout-demo")


@app.post("/checkout", response_model=Order)
def checkout(request: CheckoutRequest) -> Order:
    reserve_item(request.sku)
    response = charge(request.amount, request.idempotency_key, request.provider_mode)
    result = PaymentResult.model_validate(response)
    if result.status == "declined":
        return create_order(request.order_id, "failed")
    return create_order(request.order_id, "completed", result.charge_id)


@app.get("/orders/{order_id}", response_model=Order)
def order(order_id: str) -> Order:
    found = get_order(order_id)
    if found is None:
        raise HTTPException(status_code=404, detail="order not found")
    return found
