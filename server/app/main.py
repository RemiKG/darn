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
