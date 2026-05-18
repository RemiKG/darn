"""Darn server — FastAPI app factory and entrypoint.

- /api/* — REST + SSE (see app.api)
- everything else — the built web app from ../web/dist (SPA fallback),
  with a one-line JSON hint when the bundle isn't built yet.

The agent layer is wired at startup from app.agent.wiring when present;
otherwise honest NotConfigured fallbacks take its place. Imports of
app.agent / app.integrations are never required for the core to run.
"""

from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.api import routers
from app.config import settings
from app.demo.defects import load_defects
from app.demo.fallbacks import fallback_backends
from app.demo.orchestrator import DemoOrchestrator
from app.demo.seams import Backends
from app.health import HealthService
from app.secrets import SecretBackend, get_secret_backend
from app.sessions import SessionMiddleware
from app.sse import SseHub
from app.store import Store, get_store
from app.views import build_state

log = logging.getLogger("darn")

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _pick(result, name: str):
    """build_backends may return a dict or an attribute-style object."""
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


async def _wire_backends() -> Backends:
    """Try the agent layer; fall back honestly. One calm line either way."""
    fallback = fallback_backends()
    try:
        from app.agent.wiring import build_backends  # the agent team's seam
    except Exception as e:
        log.info(
            "agent wiring not present — running with not-configured fallbacks (%s)",
            type(e).__name__,
        )
        return fallback
    try:
        result = build_backends()
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        log.exception("agent wiring failed — falling back to not-configured backends")
        return fallback
    names = ("sabotage", "pipeline", "health", "byo_validator")
    provided = {n: _pick(result, n) for n in names}
    wired = Backends(
        sabotage=provided["sabotage"] or fallback.sabotage,
        pipeline=provided["pipeline"] or fallback.pipeline,
        health=provided["health"] or fallback.health,
        byo_validator=provided["byo_validator"] or fallback.byo_validator,
    )
    live = [n for n in names if provided[n] is not None]
    missing = [n for n in names if provided[n] is None]
    log.info(
        "agent wiring connected — live: %s%s",
        ", ".join(live) or "none",
        f"; not-configured fallback: {', '.join(missing)}" if missing else "",
    )
    return wired


def create_app(
    *,
    store: Optional[Store] = None,
    backends: Optional[Backends] = None,
    secret_backend: Optional[SecretBackend] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        the_store = store if store is not None else get_store()
        await the_store.init()
        hub = SseHub()
        load_defects()
        wired = backends if backends is not None else await _wire_backends()
        secrets = (
            secret_backend if secret_backend is not None else get_secret_backend()
        )
        orchestrator = DemoOrchestrator(
            store=the_store,
            hub=hub,
            sabotage=wired.sabotage,
            pipeline=wired.pipeline,
        )
        health = HealthService(wired.health, hub)

        async def state_view() -> dict:
            return await build_state(the_store, health)

        orchestrator.state_provider = state_view

        app.state.store = the_store
        app.state.hub = hub
        app.state.backends = wired
        app.state.secrets = secrets
        app.state.orchestrator = orchestrator
        app.state.health = health
        app.state.state_view = state_view

        await health.start()
        await orchestrator.resume()
        log.info(
            "darn server up — store=%s secrets=%s", settings.store_mode,
            settings.secrets_mode,
        )
        try:
            yield
        finally:
            await orchestrator.shutdown()
            await health.stop()

    app = FastAPI(title="Darn.", lifespan=lifespan)
    app.add_middleware(SessionMiddleware)
    for r in routers:
        app.include_router(r, prefix="/api")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"error": "not_found"}, status_code=404)
        if WEB_DIST.is_dir():
            if full_path:
                candidate = (WEB_DIST / full_path).resolve()
                try:
                    inside = candidate.is_relative_to(WEB_DIST.resolve())
                except ValueError:
                    inside = False
                if inside and candidate.is_file():
                    return FileResponse(candidate)
            index = WEB_DIST / "index.html"
            if index.is_file():
                return FileResponse(index)
        return JSONResponse(
            {"hint": "web/dist is not built yet — the API lives under /api"}
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")
