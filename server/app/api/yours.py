"""BYO endpoints — connect a real tenant, map services, disconnect & delete.

Validation goes through the ByoValidator seam (a REAL MCP initialize +
tools/list round trip in the wired deployment). Tokens live only in the
secret backend; the regular store never sees them.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.demo.seams import ByoValidationError, NotConfiguredError
from app.models import ServiceMapping

from app.secrets import byo_secret_name

router = APIRouter(prefix="/yours")


class ConnectBody(BaseModel):
    tenant_url: str
    platform_token: str


class MappingBody(BaseModel):
    service: str
    repo: str
    branch: str = "main"
    watch: bool = True


class PauseBody(BaseModel):
    service: str


class DisconnectBody(BaseModel):
    confirm_host: str


def _tenant_host(tenant_url: str) -> Optional[str]:
    raw = tenant_url.strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower()
    return host or None


@router.post("/connect")
async def connect(body: ConnectBody, request: Request):
    host = _tenant_host(body.tenant_url)
    if host is None or not body.platform_token.strip():
        return JSONResponse(
            {
                "error": "That doesn't look like a tenant URL and token.",
                "hint": "https://<env>.apps.dynatrace.com plus a platform token.",
            },
            status_code=422,
        )
    validator = request.app.state.backends.byo_validator
    try:
        services = await validator.validate(body.tenant_url, body.platform_token)
    except NotConfiguredError as e:
        return JSONResponse(
            {"error": "not_configured", "missing": e.missing}, status_code=503
        )
    except ByoValidationError as e:
        return JSONResponse({"error": e.message, "hint": e.hint}, status_code=422)

    secrets = request.app.state.secrets
    try:
        await secrets.put_secret(byo_secret_name(host), body.platform_token)
    except Exception as e:
        return JSONResponse(
            {"error": "secret_store_unavailable", "hint": str(e)}, status_code=503
        )

    store = request.app.state.store
    byo = await store.get_byo()
    byo.connected = True
    byo.tenant_host = host
    byo.services = list(services)
    await store.put_byo(byo)
    return {"ok": True, "services": services}


@router.get("")
async def get_yours(request: Request):
    store = request.app.state.store
    byo = await store.get_byo()
    summaries = await store.list_incident_summaries()
    mends = [s.model_dump(mode="json") for s in summaries if s.kind == "byo"]
    return {
        "connected": byo.connected,
        "tenant_host": byo.tenant_host,
        "services": byo.services,
        "mappings": [m.model_dump(mode="json") for m in byo.mappings],
        "github": {"installed": byo.github_installed, "repo": byo.github_repo},
        "mends": mends,
    }


@router.post("/mappings")
async def put_mapping(body: MappingBody, request: Request):
    store = request.app.state.store
    byo = await store.get_byo()
    if not byo.connected:
        return JSONResponse(
            {"error": "not_connected", "hint": "Connect your tenant first."},
            status_code=422,
        )
    if not body.repo.strip():
        # An empty repo unmaps the service (the UI's "Unmap" action).
        byo.mappings = [m for m in byo.mappings if m.service != body.service]
        await store.put_byo(byo)
        return {
            "ok": True,
            "mappings": [m.model_dump(mode="json") for m in byo.mappings],
        }
    for m in byo.mappings:
        if m.service == body.service:
            m.repo = body.repo
            m.branch = body.branch
            m.watch = body.watch
            break
    else:
        byo.mappings.append(
            ServiceMapping(
                service=body.service,
                repo=body.repo,
                branch=body.branch,
                watch=body.watch,
            )
        )
    await store.put_byo(byo)
    return {"ok": True, "mappings": [m.model_dump(mode="json") for m in byo.mappings]}


@router.post("/pause")
async def pause(body: PauseBody, request: Request):
    store = request.app.state.store
    byo = await store.get_byo()
    for m in byo.mappings:
        if m.service == body.service:
            m.paused = not m.paused
            await store.put_byo(byo)
            return {"ok": True, "service": m.service, "paused": m.paused}
    return JSONResponse({"error": "not_found"}, status_code=404)


@router.post("/disconnect")
async def disconnect(body: DisconnectBody, request: Request):
    store = request.app.state.store
    byo = await store.get_byo()
    if not byo.connected:
        return JSONResponse({"error": "not_connected"}, status_code=422)
    if body.confirm_host.strip().lower() != byo.tenant_host.lower():
        return JSONResponse(
            {
                "error": "confirm_mismatch",
                "hint": "Type the tenant host exactly to confirm.",
            },
            status_code=422,
        )
    secrets = request.app.state.secrets
    try:
        await secrets.delete_secret(byo_secret_name(byo.tenant_host))
    except Exception:
        pass  # the secret may already be gone; state still resets below
    deleted = await store.delete_incidents("byo")
    from app.models import ByoState

    await store.put_byo(ByoState())
    return {"ok": True, "deleted_incidents": deleted}


@router.get("/github/install-url")
async def github_install_url(request: Request):
    validator = request.app.state.backends.byo_validator
    url: Optional[str] = None
    try:
        url = await validator.github_install_url()
    except Exception:
        url = None
    return {"url": url, "configured": settings.github_mode == "app"}
