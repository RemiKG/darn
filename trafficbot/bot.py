"""Loose Threads synthetic shoppers.

Steady, real traffic against the shop so Davis has signal to watch. Each shopper
picks a behavior from a fixed mix, runs it, then waits a jittered beat. The whole
point of the empty-cart slice is that the `checkout-null` defect kills it: when
the shop is healthy everything is 2xx, when it's torn the designed endpoint 500s.

Config (env):
  SHOP_URL    base URL of the shop            (default http://127.0.0.1:4602)
  RATE_RPM    target requests per minute       (default 180)
  JITTER      fractional jitter on the delay   (default 0.3)
  HEALTH_PORT tiny /healthz port, 0 disables   (default 4603)

Behavior mix per request: browse catalog ~60%, happy-path buy ~25%,
empty-cart checkout ~10%, restock ~5%.
"""

from __future__ import annotations

import asyncio
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

SHOP_URL = os.environ.get("SHOP_URL", "http://127.0.0.1:4602").strip().rstrip("/")
RATE_RPM = int(os.environ.get("RATE_RPM", "180") or "180")
JITTER = float(os.environ.get("JITTER", "0.3") or "0.3")
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "4603") or "0")

SOCK_IDS = [
    "monday-heel",
    "static-cling",
    "argyle-karen",
    "lucky-odd",
    "off-duty-cloud",
    "tuesdays-revenge",
]

_down_logged = False


def _base_delay() -> float:
    return 60.0 / max(RATE_RPM, 1)


def _jittered(delay: float) -> float:
    return max(0.0, delay * (1.0 + random.uniform(-JITTER, JITTER)))


async def browse(client: httpx.AsyncClient) -> None:
    await client.get("/api/catalog")


async def happy_path(client: httpx.AsyncClient) -> None:
    """Add one or two socks, check out, and pay the quoted total."""
    cart_id = None
    for _ in range(random.randint(1, 2)):
        body = {"sock_id": random.choice(SOCK_IDS), "qty": 1}
        if cart_id:
            body["cart_id"] = cart_id
        r = await client.post("/api/cart", json=body)
        if r.status_code != 200:
            return
        cart_id = r.json().get("cart_id")
    co = await client.post("/api/checkout", json={"cart_id": cart_id})
    if co.status_code != 200:
        return
    order = co.json()
    await client.post(
        "/api/pay",
        json={"order_id": order["order_id"], "amount_cents": order["total_cents"]},
    )


async def empty_checkout(client: httpx.AsyncClient) -> None:
    """Create an empty cart and try to check it out — the checkout-null trigger."""
    r = await client.post("/api/cart", json={"sock_id": random.choice(SOCK_IDS), "qty": 0})
    if r.status_code != 200:
        return
    cart_id = r.json().get("cart_id")
    await client.post("/api/checkout", json={"cart_id": cart_id})


async def restock(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/inventory/restock",
        json={"sock_id": random.choice(SOCK_IDS), "qty": random.randint(1, 24)},
    )


def pick_behavior():
    roll = random.random()
    if roll < 0.60:
        return browse
    if roll < 0.85:
        return happy_path
    if roll < 0.95:
        return empty_checkout
    return restock


async def run() -> None:
    global _down_logged
    print(f"trafficbot → {SHOP_URL} at ~{RATE_RPM} rpm (jitter {JITTER})", flush=True)
    async with httpx.AsyncClient(base_url=SHOP_URL, timeout=10.0) as client:
        while True:
            behavior = pick_behavior()
            try:
                await behavior(client)
                if _down_logged:
                    print("shop reachable again", flush=True)
                    _down_logged = False
            except (httpx.HTTPError, OSError) as exc:
                if not _down_logged:
                    print(f"shop unreachable ({exc!r}); will keep trying quietly", flush=True)
                    _down_logged = True
            await asyncio.sleep(_jittered(_base_delay()))


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args):  # silence per-request logging
        return


def _start_health() -> None:
    if HEALTH_PORT <= 0:
        return
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"health endpoint on :{HEALTH_PORT}/healthz", flush=True)


if __name__ == "__main__":
    _start_health()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
