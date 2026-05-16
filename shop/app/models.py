"""Data shapes for the shop — products, carts, orders, and request bodies.

Money is integer cents everywhere. Prices are whole dollars for display, but we
keep them in cents because that is the only honest way to do money.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True)
class Sock:
    """A product in the catalog. `art_id` points at a sprite symbol in socks.svg."""

    id: str
    name: str
    price_cents: int
    art_id: str

    @property
    def price_dollars(self) -> str:
        # Whole-dollar prices, shown without trailing zeros (matches the storefront comp).
        return f"{self.price_cents // 100}"


@dataclass
class CartLine:
    sock_id: str
    name: str
    unit_price_cents: int
    qty: int


@dataclass
class Cart:
    id: str
    lines: list[CartLine] = field(default_factory=list)

    def line_for(self, sock_id: str) -> CartLine | None:
        for line in self.lines:
            if line.sock_id == sock_id:
                return line
        return None


@dataclass
class Order:
    id: str
    lines: list[CartLine]
    subtotal_cents: int
    total_cents: int
    status: str = "open"  # open | paid
    lead_sock: str | None = None


# ---- request bodies -------------------------------------------------------

class CartRequest(BaseModel):
    sock_id: str
    qty: int = 1
    cart_id: str | None = None


class CheckoutRequest(BaseModel):
    cart_id: str


class PayRequest(BaseModel):
    order_id: str
    amount_cents: int


class RestockRequest(BaseModel):
    sock_id: str
    qty: int
