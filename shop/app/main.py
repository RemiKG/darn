"""Loose Threads — FastAPI app wiring.

Serves the storefront, the cart/checkout/pay/inventory API, and a health check.
Unhandled errors are left to surface as real 500s (with a traceback in the logs):
the whole point of this shop is that, when it's torn, you can see the tear.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import cart, catalog, checkout, inventory, pay
from .config import DARN_URL
from .otel import init_otel

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

app = FastAPI(title="Loose Threads", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

app.include_router(catalog.router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(pay.router)
app.include_router(inventory.router)

# OpenTelemetry: real exporter when configured, total no-op otherwise.
init_otel(app)


@app.get("/", response_class=HTMLResponse)
def storefront(request: Request) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "shop.html",
        {"catalog": catalog.STATE.catalog(), "darn_url": DARN_URL},
    )


@app.get("/api/darn")
async def darn_incident() -> dict:
    """Discover a live Darn incident to link the torn-state banner at.

    Best-effort: if DARN_URL is unset or unreachable, return nothing and let the
    storefront degrade silently.
    """
    if not DARN_URL:
        return {"darn_url": None, "incident_url": None}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{DARN_URL}/api/state")
            res.raise_for_status()
            data = res.json()
        incident_id = data.get("live_incident_id")
        incident_url = f"{DARN_URL}/incident/{incident_id}" if incident_id else None
        return {"darn_url": DARN_URL, "incident_url": incident_url}
    except Exception:
        return {"darn_url": DARN_URL, "incident_url": None}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
