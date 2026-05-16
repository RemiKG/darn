"""Carts — add a sock, read a cart back. Quantities below 1 just don't add a line
(so an empty cart is a perfectly valid thing to create and check out)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .catalog import STATE
from .models import CartLine, CartRequest
from .otel import get_tracer

router = APIRouter()


def _cart_body(cart) -> dict:
    lines = [
        {
            "sock_id": line.sock_id,
            "name": line.name,
            "unit_price_cents": line.unit_price_cents,
            "qty": line.qty,
        }
        for line in cart.lines
    ]
    qty = sum(line.qty for line in cart.lines)
    subtotal_cents = sum(line.qty * line.unit_price_cents for line in cart.lines)
    return {
        "cart_id": cart.id,
        "lines": lines,
        "count": qty,
        "subtotal_cents": subtotal_cents,
    }


@router.post("/api/cart")
def add_to_cart(req: CartRequest) -> dict:
    """Add `qty` of a sock to a cart, creating the cart if needed.

    `qty` of 0 (or no matching sock) creates/returns the cart without adding a
    line — that's how an empty cart comes to exist.
    """
    with get_tracer().start_as_current_span("cart.add"):
        cart = STATE.get_cart(req.cart_id) or STATE.new_cart()

        if req.qty > 0:
            sock = STATE.sock(req.sock_id)
            if sock is None:
                raise HTTPException(status_code=404, detail="no such sock")
            line = cart.line_for(sock.id)
            if line is None:
                cart.lines.append(CartLine(sock.id, sock.name, sock.price_cents, req.qty))
            else:
                line.qty += req.qty

        return _cart_body(cart)


@router.get("/api/cart")
def get_cart(cart_id: str) -> dict:
    cart = STATE.get_cart(cart_id)
    if cart is None:
        raise HTTPException(status_code=404, detail="cart not found")
    return _cart_body(cart)
