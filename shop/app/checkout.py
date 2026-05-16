"""Checkout — turn a cart into an order, total it up (subtotal + tax)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .catalog import STATE
from .models import CartLine, CheckoutRequest
from .otel import get_tracer
from .state import tax_cents

router = APIRouter()


def _lead_sock(lines: list[CartLine]) -> str | None:
    """The headline item for the order, used on the confirmation screen.

    The priciest sock in the cart ("The Monday Heel and 2 more"). Empty carts
    have no lead item, so this returns None for them.
    """
    head = max(lines, key=lambda line: line.unit_price_cents) if lines else None
    return head.sock_id if head else None


def _order_body(order) -> dict:
    return {
        "order_id": order.id,
        "subtotal_cents": order.subtotal_cents,
        "total_cents": order.total_cents,
        "lead_sock": order.lead_sock,
        "status": order.status,
    }


@router.post("/api/checkout")
def checkout(req: CheckoutRequest) -> dict:
    with get_tracer().start_as_current_span("checkout.create_order"):
        cart = STATE.get_cart(req.cart_id)
        if cart is None:
            raise HTTPException(status_code=404, detail="cart not found")

        subtotal_cents = sum(line.qty * line.unit_price_cents for line in cart.lines)
        total_cents = subtotal_cents + tax_cents(subtotal_cents)

        order = STATE.create_order(
            cart, subtotal_cents, total_cents, lead_sock=_lead_sock(cart.lines)
        )
        return _order_body(order)
