from .models import Order

_INITIAL_STOCK = {"sku-basic": 100, "sku-pro": 10}

_orders: dict[str, Order] = {}
_stock: dict[str, int] = dict(_INITIAL_STOCK)


def create_order(order_id: str, status: str, charge_id: str | None = None) -> Order:
    order = Order(order_id=order_id, status=status, charge_id=charge_id)
    _orders[order_id] = order
    return order


def get_order(order_id: str) -> Order | None:
    return _orders.get(order_id)


def reserve_item(sku: str) -> None:
    _stock[sku] -= 1


def reset_state() -> None:
    _orders.clear()
    _stock.clear()
    _stock.update(_INITIAL_STOCK)
    from .payments import reset_charges

    reset_charges()
