"""Loose Threads: healthy endpoints all pass, and each defect breaks exactly its
designed endpoint while leaving the others alone. Reverting (healthy content)
restores 2xx — these tests are the proof the demo's tears actually tear."""

from __future__ import annotations

import time
import traceback

import pytest

from .conftest import load_patch


# ---- helpers --------------------------------------------------------------

def _buy(client, sock_ids):
    cart_id = None
    for sid in sock_ids:
        body = {"sock_id": sid, "qty": 1}
        if cart_id:
            body["cart_id"] = cart_id
        r = client.post("/api/cart", json=body)
        assert r.status_code == 200
        cart_id = r.json()["cart_id"]
    return cart_id


def _empty_cart(client):
    r = client.post("/api/cart", json={"sock_id": "monday-heel", "qty": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["lines"] == []
    return body["cart_id"]


# ---- healthy --------------------------------------------------------------

def test_storefront_and_health(shop_app):
    client = shop_app()
    assert client.get("/healthz").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Loose Threads" in page.text
    assert "Fine socks, loosely threaded." in page.text


def test_catalog_has_six_socks(shop_app):
    client = shop_app()
    socks = client.get("/api/catalog").json()["socks"]
    assert len(socks) == 6
    names = {s["name"]: s["price_cents"] for s in socks}
    assert names == {
        "The Monday Heel": 900,
        "Static Cling": 1100,
        "Argyle Karen": 1200,
        "The Lucky Odd": 700,
        "Off-Duty Cloud": 1000,
        "Tuesday's Revenge": 900,
    }


def test_catalog_fast_when_healthy(shop_app):
    client = shop_app()
    start = time.perf_counter()
    assert client.get("/api/catalog").status_code == 200
    assert time.perf_counter() - start < 1.0


def test_happy_path_totals_exact(shop_app):
    client = shop_app()
    # $9 + $11 + $7 = $27 subtotal; tax 8.875% rounds to 240c; total 2940c.
    cart_id = _buy(client, ["monday-heel", "static-cling", "lucky-odd"])
    assert client.get(f"/api/cart?cart_id={cart_id}").json()["subtotal_cents"] == 2700
    order = client.post("/api/checkout", json={"cart_id": cart_id}).json()
    assert order["subtotal_cents"] == 2700
    assert order["total_cents"] == 2940  # integer-cents exact
    pay = client.post(
        "/api/pay", json={"order_id": order["order_id"], "amount_cents": order["total_cents"]}
    )
    assert pay.status_code == 200
    assert pay.json()["status"] == "paid"


def test_empty_cart_checkout_ok_when_healthy(shop_app):
    client = shop_app()
    cart_id = _empty_cart(client)
    order = client.post("/api/checkout", json={"cart_id": cart_id})
    assert order.status_code == 200
    assert order.json()["total_cents"] == 0


def test_restock_ok_when_healthy(shop_app):
    client = shop_app()
    r = client.post("/api/inventory/restock", json={"sock_id": "monday-heel", "qty": 10})
    assert r.status_code == 200
    assert r.json()["stock"] >= 10


# ---- defects --------------------------------------------------------------

def test_checkout_null_defect(shop_app):
    client = shop_app(overrides=load_patch("checkout-null"))
    # empty cart → 500
    empty_id = _empty_cart(client)
    broken = client.post("/api/checkout", json={"cart_id": empty_id})
    assert broken.status_code == 500
    # non-empty cart → still 200
    cart_id = _buy(client, ["argyle-karen"])
    ok = client.post("/api/checkout", json={"cart_id": cart_id})
    assert ok.status_code == 200


def test_checkout_null_reverts(shop_app):
    client = shop_app()  # healthy content == revert
    empty_id = _empty_cart(client)
    assert client.post("/api/checkout", json={"cart_id": empty_id}).status_code == 200


def test_catalog_stampede_defect(shop_app):
    client = shop_app(overrides=load_patch("catalog-stampede"))
    start = time.perf_counter()
    r = client.get("/api/catalog")
    elapsed = time.perf_counter() - start
    assert r.status_code == 200
    assert elapsed > 1.0, f"expected degraded latency, got {elapsed:.3f}s"


def test_penny_shaver_defect(shop_app):
    client = shop_app(overrides=load_patch("penny-shaver"))
    cart_id = _buy(client, ["monday-heel"])  # $9 → drifts a cent under the float total
    order = client.post("/api/checkout", json={"cart_id": cart_id}).json()
    pay = client.post(
        "/api/pay", json={"order_id": order["order_id"], "amount_cents": order["total_cents"]}
    )
    assert pay.status_code == 500


def test_penny_shaver_reverts(shop_app):
    client = shop_app()
    cart_id = _buy(client, ["monday-heel"])
    order = client.post("/api/checkout", json={"cart_id": cart_id}).json()
    pay = client.post(
        "/api/pay", json={"order_id": order["order_id"], "amount_cents": order["total_cents"]}
    )
    assert pay.status_code == 200


def test_inventory_grenade_defect(shop_app):
    client = shop_app(overrides=load_patch("inventory-grenade"))
    r = client.post("/api/inventory/restock", json={"sock_id": "monday-heel", "qty": 10})
    assert r.status_code == 500


def test_inventory_grenade_reverts(shop_app):
    client = shop_app()
    r = client.post("/api/inventory/restock", json={"sock_id": "monday-heel", "qty": 10})
    assert r.status_code == 200


# ---- tracebacks: the 500-producing defects must clearly name their function ----

def _capture_traceback(exc_info) -> str:
    return "".join(traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb))


def test_checkout_null_traceback_names_function(shop_app):
    client = shop_app(overrides=load_patch("checkout-null"), raise_server_exceptions=True)
    empty_id = _empty_cart(client)
    with pytest.raises(AttributeError) as exc_info:
        client.post("/api/checkout", json={"cart_id": empty_id})
    tb = _capture_traceback(exc_info)
    assert "checkout.py" in tb and "_lead_sock" in tb
    assert "'NoneType' object has no attribute 'sock_id'" in tb


def test_penny_shaver_traceback_names_function(shop_app):
    client = shop_app(overrides=load_patch("penny-shaver"), raise_server_exceptions=True)
    cart_id = _buy(client, ["monday-heel"])
    order = client.post("/api/checkout", json={"cart_id": cart_id}).json()
    with pytest.raises(Exception) as exc_info:
        client.post("/api/pay", json={"order_id": order["order_id"], "amount_cents": order["total_cents"]})
    tb = _capture_traceback(exc_info)
    assert "pay.py" in tb and "in pay" in tb
    assert "PaymentError" in tb and "reconciliation" in tb


def test_inventory_grenade_traceback_names_function(shop_app):
    client = shop_app(overrides=load_patch("inventory-grenade"), raise_server_exceptions=True)
    with pytest.raises(Exception) as exc_info:
        client.post("/api/inventory/restock", json={"sock_id": "monday-heel", "qty": 10})
    tb = _capture_traceback(exc_info)
    assert "inventory.py" in tb and "in restock" in tb
    assert "InventoryError" in tb


@pytest.mark.parametrize("key", ["checkout-null", "catalog-stampede", "penny-shaver", "inventory-grenade"])
def test_patch_is_one_small_file(key):
    files = load_patch(key)
    assert len(files) == 1, f"{key} should patch exactly one file"
    rel, content = files[0]
    assert rel.endswith(".py")
    assert content.strip(), "sabotaged content must not be empty"
