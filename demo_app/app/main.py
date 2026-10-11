
from fastapi import FastAPI, HTTPException

from .models import CheckoutRequest, CheckoutResponse, Order
from .payments import charge
from .store import create_order, get_order

app = FastAPI(title="ResolveLoop Checkout Demo")


@app.post("/checkout", response_model=CheckoutResponse)
def checkout(request: CheckoutRequest):
    """Process a checkout request."""

    try:
        payment = charge(
            amount=request.amount,
            idempotency_key=request.idempotency_key,
            mode=request.mode,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Payment gateway timeout",
        ) from None

    # BUG 1: Assumes the gateway always returns a dictionary.
    # Malformed responses return None, causing TypeError.
    status = payment["status"]

    if status == "success":
        order = create_order(request.order_id, "completed")
    else:
        order = create_order(request.order_id, "failed")

    return CheckoutResponse(
        order_id=order.order_id,
        status=order.status,
    )


@app.get("/orders/{order_id}", response_model=Order)
def read_order(order_id: str):
    """Retrieve an existing order."""

    order = get_order(order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return order
