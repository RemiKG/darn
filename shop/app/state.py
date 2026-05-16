"""In-memory shop state — carts, orders, and the stock ledger.

It's a prop, so state lives in process: a deployed instance keeps its carts and
orders for as long as it runs. The `_read_*` helpers simulate the latency of a
real stock database so the catalog page reads like it talks to one — that seam
is deliberate, and one of the demo defects leans on it.
"""

from __future__ import annotations

import threading
import time
import uuid

from .models import Cart, CartLine, Order, Sock

# ---- pricing --------------------------------------------------------------
# Sales tax, applied at checkout. Held in hundred-thousandths so the integer
# math below is exact — money never touches a float on the healthy path.
TAX_RATE_BP = 8875  # 8.875%
TAX_RATE = TAX_RATE_BP / 100_000  # same rate as a float, for callers that want it


def tax_cents(subtotal_cents: int) -> int:
    """Tax on a subtotal, rounded half-up, integer-only."""
    return (subtotal_cents * TAX_RATE_BP + 50_000) // 100_000


# ---- simulated datastore latency -----------------------------------------
# One round-trip to the stock database. Small, but not free — exactly what you'd
# pay per query against a real store.
_STOCK_QUERY_SECONDS = 0.30


def _db_round_trip() -> None:
    time.sleep(_STOCK_QUERY_SECONDS)


class ShopState:
    """The whole shop's mutable state behind one lock."""

    def __init__(self, catalog: list[Sock]) -> None:
        self._lock = threading.RLock()
        self._catalog = {sock.id: sock for sock in catalog}
        # Every sock starts comfortably stocked.
        self._stock: dict[str, int] = {sock.id: 120 for sock in catalog}
        self._carts: dict[str, Cart] = {}
        self._orders: dict[str, Order] = {}

    # ---- catalog / stock --------------------------------------------------
    def catalog(self) -> list[Sock]:
        return list(self._catalog.values())

    def sock(self, sock_id: str) -> Sock | None:
        return self._catalog.get(sock_id)

    def stock_snapshot(self) -> dict[str, int]:
        """All stock levels in one read — the cheap path the catalog uses."""
        with self._lock:
            return dict(self._stock)

    def read_stock(self, sock_id: str) -> int:
        """Stock for a single sock, fetched from the (simulated) datastore.

        Used where one sock's level is genuinely needed — a per-row round-trip.
        """
        _db_round_trip()
        with self._lock:
            return self._stock.get(sock_id, 0)

    def set_stock(self, sock_id: str, qty: int) -> None:
        with self._lock:
            self._stock[sock_id] = qty

    # ---- carts ------------------------------------------------------------
    def new_cart(self) -> Cart:
        cart = Cart(id=f"cart_{uuid.uuid4().hex[:12]}")
        with self._lock:
            self._carts[cart.id] = cart
        return cart

    def get_cart(self, cart_id: str | None) -> Cart | None:
        if not cart_id:
            return None
        with self._lock:
            return self._carts.get(cart_id)

    # ---- orders -----------------------------------------------------------
    def create_order(
        self, cart: Cart, subtotal_cents: int, total_cents: int, lead_sock: str | None = None
    ) -> Order:
        order = Order(
            id=f"ord_{uuid.uuid4().hex[:12]}",
            lines=[CartLine(l.sock_id, l.name, l.unit_price_cents, l.qty) for l in cart.lines],
            subtotal_cents=subtotal_cents,
            total_cents=total_cents,
            lead_sock=lead_sock,
        )
        with self._lock:
            self._orders[order.id] = order
        return order

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def save_order(self, order: Order) -> None:
        with self._lock:
            self._orders[order.id] = order
