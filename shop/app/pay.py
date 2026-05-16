"""Payment — charge an order, but only once the books reconcile.

Before moving money we re-derive the charge from the order's own line items and
require it to match the total we quoted at checkout, to the cent. If the two
ever disagree something is wrong with our pricing and we refuse the charge
rather than bill the customer the wrong amount.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .catalog import STATE
from .models import PayRequest
from .otel import get_tracer
from .state import tax_cents

router = APIRouter()


class PaymentError(RuntimeError):
    """Raised when the re-derived charge doesn't reconcile with the order total."""


@router.post("/api/pay")
def pay(req: PayRequest) -> dict:
    with get_tracer().start_as_current_span("pay.charge"):
        order = STATE.get_order(req.order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")

        # Re-derive the charge straight from the order, server-side.
        subtotal_cents = sum(line.qty * line.unit_price_cents for line in order.lines)
        charge_cents = subtotal_cents + tax_cents(subtotal_cents)

        if charge_cents != order.total_cents:
            raise PaymentError(
                f"charge reconciliation failed for {order.id}: "
                f"re-derived {charge_cents} != quoted {order.total_cents}"
            )

        if req.amount_cents != order.total_cents:
            raise HTTPException(status_code=400, detail="amount does not match order total")

        order.status = "paid"
        STATE.save_order(order)
        return {"order_id": order.id, "status": "paid", "amount_cents": req.amount_cents}
