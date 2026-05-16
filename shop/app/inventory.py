"""Inventory — restock a sock. Restocking only ever grows stock; a result below
zero would mean a bad request, so we guard against it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .catalog import STATE
from .models import RestockRequest
from .otel import get_tracer

router = APIRouter()


class InventoryError(RuntimeError):
    """Raised when a restock would leave stock in an impossible state."""


@router.post("/api/inventory/restock")
def restock(req: RestockRequest) -> dict:
    with get_tracer().start_as_current_span("inventory.restock"):
        if req.qty < 0:
            raise HTTPException(status_code=400, detail="restock qty cannot be negative")

        current = STATE.read_stock(req.sock_id)
        new_total = current + req.qty

        # Sanity guard: a restock should never drive stock below zero.
        if new_total < 0:
            raise InventoryError(
                f"restock would leave {req.sock_id} at {new_total}"
            )

        STATE.set_stock(req.sock_id, new_total)
        return {"sock_id": req.sock_id, "stock": new_total}
