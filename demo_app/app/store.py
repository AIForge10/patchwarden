
from .models import Order
from .payments import reset_charges

_orders: dict[str, Order] = {}


def create_order(order_id: str, status: str) -> Order:
    """Create or update an order."""
    order = Order(order_id=order_id, status=status)
    _orders[order_id] = order
    return order


def get_order(order_id: str) -> Order | None:
    """Retrieve an order by ID."""
    return _orders.get(order_id)


def get_order_count() -> int:
    """Return the number of stored orders."""
    return len(_orders)


def reset_state() -> None:
    """Reset orders and charges between tests."""
    _orders.clear()
    reset_charges()
