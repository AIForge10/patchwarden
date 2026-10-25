from .models import Order

_orders: dict[str, Order] = {}


def create_order(order_id: str, status: str, charge_id: str | None = None) -> Order:
    order = Order(order_id=order_id, status=status, charge_id=charge_id)
    _orders[order_id] = order
    return order


def get_order(order_id: str) -> Order | None:
    return _orders.get(order_id)


def reset_state() -> None:
    _orders.clear()
    from .payments import reset_charges

    reset_charges()
