"""GET/PUT /api/settings — defaults applied, locked toggles enforced."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.settings_model import (
    DarnSettings,
    LOCKED_FIELDS,
    enforce_locked,
    merge_sections,
)
from app.store import Store

router = APIRouter()


async def _current(store: Store) -> DarnSettings:
    stored = await store.get_settings()
    if not stored:
        return enforce_locked(DarnSettings())
    base = DarnSettings().model_dump()
    try:
        merged = DarnSettings.model_validate(merge_sections(base, stored))
    except ValidationError:
        merged = DarnSettings()
    return enforce_locked(merged)


@router.get("/settings")
async def get_settings(request: Request):
    current = await _current(request.app.state.store)
    return current.model_dump(mode="json")


@router.put("/settings")
async def put_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "invalid_settings", "hint": "Send a JSON object."},
            status_code=422,
        )

    # Locked toggles are constants; flipping one is rejected, not ignored.
    for (section, field), (constant, hint) in LOCKED_FIELDS.items():
        section_body = body.get(section)
        if isinstance(section_body, dict) and field in section_body:
            if bool(section_body[field]) != constant:
                return JSONResponse(
                    {"error": f"'{section}.{field}' is locked", "hint": hint},
                    status_code=422,
                )

    current = await _current(request.app.state.store)
    merged = merge_sections(current.model_dump(), body)
    try:
        validated = DarnSettings.model_validate(merged)
    except ValidationError as e:
        detail = [
            {"loc": [str(p) for p in err["loc"]], "msg": err["msg"]}
            for err in e.errors()
        ]
        return JSONResponse(
            {"error": "invalid_settings", "detail": detail}, status_code=422
        )
    enforce_locked(validated)
    data = validated.model_dump(mode="json")
    await request.app.state.store.put_settings(data)
    return data


@router.post("/settings/delete-incidents")
async def delete_incidents(request: Request):
    """Data & privacy: bulk-delete stored BYO incidents. Demo incidents are
    the public archive and stay."""
    deleted = await request.app.state.store.delete_incidents("byo")
    return {"ok": True, "deleted": deleted}


@router.post("/settings/delete-tokens")
async def delete_tokens(request: Request):
    """Data & privacy: remove the BYO platform token from the secret backend
    now. Mappings stay; watching stops working until a new token is connected."""
    store = request.app.state.store
    byo = await store.get_byo()
    if not byo.connected or not byo.tenant_host:
        return {"ok": True, "deleted": False}
    from app.secrets import byo_secret_name

    try:
        await request.app.state.secrets.delete_secret(
            byo_secret_name(byo.tenant_host)
        )
    except Exception:
        return JSONResponse(
            {"error": "secret_store_unavailable"}, status_code=503
        )
    return {"ok": True, "deleted": True}
