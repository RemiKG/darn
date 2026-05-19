"""Shared fakes and harness: an ASGI client with the lifespan running, plus
fake seam implementations that drive a full incident deterministically."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Callable, Optional

import httpx
import pytest

from app import models
from app.config import settings
from app.demo.fallbacks import fallback_backends
from app.demo.seams import Backends, ByoValidationError
from app.main import create_app
from app.secrets import MemorySecretBackend
from app.store.memory import MemoryStore


@pytest.fixture(autouse=True)
def neutral_env(monkeypatch):
    """Tests never depend on the developer machine's env."""
    monkeypatch.setattr(settings, "dt_environment", "")
    monkeypatch.setattr(settings, "dt_platform_token", "")
    monkeypatch.setattr(settings, "dt_api_token", "")
    monkeypatch.setattr(settings, "github_repo", "")
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_app_id", "")
    monkeypatch.setattr(settings, "github_app_private_key_b64", "")
    monkeypatch.setattr(settings, "gcp_project", "")
    monkeypatch.setattr(settings, "shop_url", "")
    yield


# ------------------------------------------------------------------- fakes

class FakeSabotage:
    def __init__(self) -> None:
        self.commits: list[str] = []
        self.merged: list[str] = []
        self.closed: list[str] = []
        self.reverted: list[str] = []

    async def commit_defect(self, defect_key: str) -> dict:
        self.commits.append(defect_key)
        return {
            "sha": "9b1f2e7c0ffee",
            "message": f"sabotage: {defect_key}",
            "files": ["shop/app/checkout.py"],
        }

    async def revert(self, incident) -> str:
        self.reverted.append(incident.id)
        return "rev4f2c91d"

    async def merge_pr(self, incident) -> None:
        self.merged.append(incident.id)

    async def close_pr(self, incident) -> None:
        self.closed.append(incident.id)


class FakePipeline:
    """Drives all six stages instantly; an optional gate holds diagnosis so
    tests can poke at intermediate states."""

    def __init__(self, hold_diagnose: Optional[asyncio.Event] = None) -> None:
        self.hold_diagnose = hold_diagnose

    async def run_detect(self, incident, emitter) -> None:
        incident.problem_id = "P-25061123"
        incident.problem_url = "https://tenant.example/problems/P-25061123"
        await emitter.emit_receipt(
            "detected",
            models.DavisProblemReceipt(
                problem_id="P-25061123",
                title="Failure rate increase",
                entity="loose-threads-shop",
                label="Davis problem",
            ),
        )
        await emitter.stage_done("detected")

    async def run_diagnose_fix_pr(self, incident, emitter) -> None:
        if self.hold_diagnose is not None:
            await self.hold_diagnose.wait()
        await emitter.stage_started("diagnosed")
        await emitter.emit_receipt(
            "diagnosed",
            models.DqlReceipt(
                query="fetch spans, from: now() - 30m | filter request.is_failed == true",
                group="numbers",
                label="the numbers",
            ),
        )
        await emitter.stage_done("diagnosed")
        await emitter.stage_started("fix_written")
        await emitter.emit_receipt(
            "fix_written",
            models.ProposedDiffReceipt(
                files=["shop/app/checkout.py"], diff="- broken\n+ mended", label="the fix"
            ),
        )
        await emitter.stage_done("fix_written")
        await emitter.stage_started("pr_open")
        incident.pr_number = 48
        await emitter.emit_receipt(
            "pr_open",
            models.PrReceipt(
                repo="remikg/loose-threads",
                branch="darn/fix-checkout-null",
                number=48,
                title="Mend: null cart at checkout",
                label="PR",
            ),
        )
        await emitter.stage_done("pr_open")
        await emitter.set_medic(
            models.MedicTrace(
                rows=[
                    models.MedicRow(tool="execute_dql", kind="mcp", calls=3, seconds=1.2)
                ],
                tokens=19_619,
                cost_usd=0.0381,
                wall_s=24.0,
            )
        )

    async def run_verify(self, incident, emitter) -> None:
        await emitter.stage_started("verified")
        await emitter.emit_receipt(
            "verified",
            models.ReplayReceipt(
                method="POST",
                path="/api/checkout",
                before_status=500,
                after_status=200,
                label="replay",
            ),
        )
        await emitter.emit_receipt(
            "verified",
            models.ClosureReceipt(
                problem_id="P-25061123", closed_at="03:09:02", label="closure"
            ),
        )
        await emitter.stage_done("verified")


class FakeHealth:
    async def health_card(self) -> models.HealthCard:
        return models.HealthCard(
            status="ok", error_rate=0.31, p95_ms=412.0, rpm=184.0, source="dql"
        )


class FakeByoValidator:
    async def validate(self, tenant_url: str, platform_token: str):
        if "unreachable" in tenant_url:
            raise ByoValidationError(
                "Couldn't reach the tenant",
                "check the URL region (apps.dynatrace.com vs live.dynatrace.com)",
            )
        return [{"name": "storefront-api", "health": "ok"}]

    async def github_install_url(self):
        return None


def fake_backends(hold_diagnose: Optional[asyncio.Event] = None) -> Backends:
    return Backends(
        sabotage=FakeSabotage(),
        pipeline=FakePipeline(hold_diagnose),
        health=FakeHealth(),
        byo_validator=FakeByoValidator(),
    )


# ----------------------------------------------------------------- harness

class StreamingASGITransport(httpx.AsyncBaseTransport):
    """httpx's stock ASGITransport buffers the whole body until the app
    returns — useless for infinite SSE streams. This one runs the app as a
    task and hands chunks over as they are sent."""

    def __init__(self, app) -> None:
        self.app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = b""
        async for chunk in request.stream:
            body += chunk

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "root_path": "",
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "server": (request.url.host, request.url.port or 80),
            "client": ("testclient", 50000),
        }

        chunks: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        started = asyncio.Event()
        status_headers: dict = {}
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()  # idle until the app task is cancelled

        async def send(message):
            if message["type"] == "http.response.start":
                status_headers["status"] = message["status"]
                status_headers["headers"] = message.get("headers", [])
                started.set()
            elif message["type"] == "http.response.body":
                data = message.get("body", b"")
                if data:
                    await chunks.put(data)
                if not message.get("more_body", False):
                    await chunks.put(None)

        task = asyncio.create_task(self.app(scope, receive, send))
        task.add_done_callback(lambda _t: chunks.put_nowait(None))

        await asyncio.wait(
            [task, asyncio.ensure_future(started.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not started.is_set():
            exc = task.exception()
            raise exc if exc else AssertionError("app ended without a response")

        class QueueStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    chunk = await chunks.get()
                    if chunk is None:
                        break
                    yield chunk

            async def aclose(self):
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        return httpx.Response(
            status_code=status_headers["status"],
            headers=status_headers["headers"],
            stream=QueueStream(),
        )


@asynccontextmanager
async def app_client(
    backends: Optional[Backends] = None,
    store: Optional[MemoryStore] = None,
):
    """A running app (lifespan active) + an httpx client with its own cookies.

    Defaults to the core's own NotConfigured fallbacks so test outcomes never
    depend on whether the parallel agent layer is present in the checkout.
    """
    app = create_app(
        store=store if store is not None else MemoryStore(),
        backends=backends if backends is not None else fallback_backends(),
        secret_backend=MemorySecretBackend(),
    )
    async with app.router.lifespan_context(app):
        transport = StreamingASGITransport(app)
        client = httpx.AsyncClient(transport=transport, base_url="http://darn.test")
        try:
            yield client, app
        finally:
            await client.aclose()


def second_client(app) -> httpx.AsyncClient:
    """A second visitor: fresh cookie jar, same app."""
    return httpx.AsyncClient(
        transport=StreamingASGITransport(app), base_url="http://darn.test"
    )


async def wait_for(
    fetch: Callable, predicate: Callable[[dict], bool], timeout: float = 5.0
) -> dict:
    """Poll an async fetch() until predicate(result) is true."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = await fetch()
        if predicate(last):
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(f"condition not reached in {timeout}s; last={last!r}")


def stage_state(incident: dict, key: str) -> str:
    for s in incident["stages"]:
        if s["key"] == key:
            return s["state"]
    raise KeyError(key)
