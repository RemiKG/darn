"""The honest-fallback path: no agent layer, no credentials, no fakes."""

from __future__ import annotations

import sys

import httpx

from app.main import create_app
from app.secrets import MemorySecretBackend
from app.store.memory import MemoryStore
from tests.conftest import StreamingASGITransport, app_client, fake_backends


async def test_boot_without_agent_package(monkeypatch):
    """The core must come up (and refuse honestly) when app.agent is absent."""
    monkeypatch.setitem(sys.modules, "app.agent.wiring", None)  # import halts
    app = create_app(
        store=MemoryStore(), backends=None, secret_backend=MemorySecretBackend()
    )
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(
            transport=StreamingASGITransport(app), base_url="http://darn.test"
        )
        try:
            r = await client.get("/api/state")
            assert r.status_code == 200
            assert r.json()["health"]["source"] == "unavailable"
            r2 = await client.post(
                "/api/demo/tear", json={"defect": "checkout-null"}
            )
            assert r2.status_code == 503
            assert r2.json()["error"] == "not_configured"
        finally:
            await client.aclose()


async def test_state_shape_when_nothing_configured():
    async with app_client() as (client, _app):
        r = await client.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert data["dynatrace"] == {"configured": False, "mcp_ok": False}
        assert data["github"] == {"configured": False, "mode": "none"}
        assert data["live_incident_id"] is None
        assert data["cooldown_until"] is None
        assert data["mended"] == []
        assert data["last_mend"] is None
        assert data["byo_configured"] is False
        assert data["repo_url"] == ""
        assert data["tenant_url"] == ""
        assert data["health"]["status"] == "unavailable"
        assert data["health"]["source"] == "unavailable"
        assert (
            data["health"]["reason"] == "telemetry not connected on this deployment"
        )


async def test_session_cookie_set_on_first_response():
    async with app_client() as (client, _app):
        r = await client.get("/api/state")
        cookie = r.headers.get("set-cookie", "")
        assert "darn_session=" in cookie
        assert "HttpOnly" in cookie
        # second request reuses the cookie — no new set-cookie
        r2 = await client.get("/api/state")
        assert "set-cookie" not in r2.headers


async def test_tear_refuses_503_when_not_configured():
    async with app_client() as (client, _app):
        r = await client.post("/api/demo/tear", json={"defect": "checkout-null"})
        assert r.status_code == 503
        data = r.json()
        assert data["error"] == "not_configured"
        assert isinstance(data["missing"], list) and data["missing"]


async def test_tear_unknown_defect_422():
    async with app_client() as (client, _app):
        r = await client.post("/api/demo/tear", json={"defect": "nope"})
        assert r.status_code == 422


async def test_health_card_endpoint():
    async with app_client() as (client, _app):
        r = await client.get("/api/health-card")
        assert r.status_code == 200
        assert r.json()["status"] == "unavailable"


async def test_incidents_empty_and_404():
    async with app_client() as (client, _app):
        r = await client.get("/api/incidents")
        assert r.status_code == 200
        assert r.json() == {"incidents": []}
        r2 = await client.get("/api/incidents/inc-doesnotexist")
        assert r2.status_code == 404
        r3 = await client.post("/api/incidents/inc-doesnotexist/presence")
        assert r3.status_code == 404


async def test_byo_connect_503_without_validator():
    async with app_client() as (client, _app):
        r = await client.post(
            "/api/yours/connect",
            json={
                "tenant_url": "https://abc12345.apps.dynatrace.com",
                "platform_token": "dt0s16.token",
            },
        )
        assert r.status_code == 503
        assert r.json()["error"] == "not_configured"


async def test_byo_connect_and_disconnect_with_validator():
    async with app_client(backends=fake_backends()) as (client, _app):
        r = await client.post(
            "/api/yours/connect",
            json={
                "tenant_url": "https://abc12345.apps.dynatrace.com",
                "platform_token": "dt0s16.token",
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["services"][0]["name"] == "storefront-api"

        r2 = await client.get("/api/yours")
        data = r2.json()
        assert data["connected"] is True
        assert data["tenant_host"] == "abc12345.apps.dynatrace.com"

        # mapping upsert
        r3 = await client.post(
            "/api/yours/mappings",
            json={"service": "storefront-api", "repo": "remikg/storefront"},
        )
        assert r3.status_code == 200
        assert r3.json()["mappings"][0]["service"] == "storefront-api"

        # typed-confirm must match the tenant host
        bad = await client.post(
            "/api/yours/disconnect", json={"confirm_host": "wrong.host"}
        )
        assert bad.status_code == 422
        good = await client.post(
            "/api/yours/disconnect",
            json={"confirm_host": "abc12345.apps.dynatrace.com"},
        )
        assert good.status_code == 200
        r4 = await client.get("/api/yours")
        assert r4.json()["connected"] is False


async def test_byo_connect_validation_error_422():
    async with app_client(backends=fake_backends()) as (client, _app):
        r = await client.post(
            "/api/yours/connect",
            json={
                "tenant_url": "https://unreachable.apps.dynatrace.com",
                "platform_token": "dt0s16.token",
            },
        )
        assert r.status_code == 422
        assert "hint" in r.json()


async def test_spa_fallback_hint_without_dist():
    async with app_client() as (client, _app):
        r = await client.get("/some/where")
        # web/dist may or may not be built in this checkout; both are honest
        if r.headers.get("content-type", "").startswith("application/json"):
            assert "hint" in r.json()
        else:
            assert r.status_code == 200
