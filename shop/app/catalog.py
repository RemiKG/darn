"""The catalog — six socks, and the endpoint that lists them with live stock."""

from __future__ import annotations

from fastapi import APIRouter

from .models import Sock
from .otel import get_tracer
from .state import ShopState

# The shop's six products. Prices are whole dollars (kept in cents); each art_id
# names a sprite symbol in static/socks.svg.
SOCKS: list[Sock] = [
    Sock("monday-heel", "The Monday Heel", 900, "sock-monday-heel"),
    Sock("static-cling", "Static Cling", 1100, "sock-static-cling"),
    Sock("argyle-karen", "Argyle Karen", 1200, "sock-argyle-karen"),
    Sock("lucky-odd", "The Lucky Odd", 700, "sock-lucky-odd"),
    Sock("off-duty-cloud", "Off-Duty Cloud", 1000, "sock-off-duty-cloud"),
