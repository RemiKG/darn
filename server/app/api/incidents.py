"""Incident endpoints: list, detail, presence, needle, approve/decline, medic, SSE."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.demo.orchestrator import (
    HeldError,
    NotFoundError,
    NotHolderError,
    WrongStageError,
)
from app.models import MedicTrace
from app.sessions import session_id
from app.sse import SSE_HEADERS, sse_frame
from app.views import incident_to_json

router = APIRouter(prefix="/incidents")

_NOT_FOUND = JSONResponse({"error": "not_found"}, status_code=404)


@router.get("")
async def list_incidents(request: Request):
    summaries = await request.app.state.store.list_incident_summaries()
    return {
        "incidents": [
            s.model_dump(mode="json") for s in summaries if s.status != "live"
        ]
    }


@router.get("/{incident_id}")
async def get_incident(incident_id: str, request: Request):
    inc = await request.app.state.orchestrator.get_incident(incident_id)
    if inc is None:
        return _NOT_FOUND
    return incident_to_json(inc)


@router.post("/{incident_id}/presence")
async def presence(incident_id: str, request: Request):
    orch = request.app.state.orchestrator
    try:
        return await orch.presence(session_id(request), incident_id)
    except NotFoundError:
        return _NOT_FOUND


@router.post("/{incident_id}/pickup")
async def pickup(incident_id: str, request: Request):
    orch = request.app.state.orchestrator
    try:
        return await orch.pickup(session_id(request), incident_id)
    except NotFoundError:
        return _NOT_FOUND
    except WrongStageError:
        return JSONResponse({"error": "wrong_stage"}, status_code=409)
    except HeldError:
        return JSONResponse({"error": "held"}, status_code=409)


@router.post("/{incident_id}/approve")
async def approve(incident_id: str, request: Request):
    orch = request.app.state.orchestrator
    try:
        await orch.approve(session_id(request), incident_id)
    except NotFoundError:
        return _NOT_FOUND
    except NotHolderError:
        return JSONResponse({"error": "not_holder"}, status_code=403)
    except WrongStageError:
        return JSONResponse({"error": "wrong_stage"}, status_code=409)
    return {"ok": True}


@router.post("/{incident_id}/decline")
async def decline(incident_id: str, request: Request):
    orch = request.app.state.orchestrator
    try:
        await orch.decline(session_id(request), incident_id)
    except NotFoundError:
        return _NOT_FOUND
    except NotHolderError:
        return JSONResponse({"error": "not_holder"}, status_code=403)
    except WrongStageError:
        return JSONResponse({"error": "wrong_stage"}, status_code=409)
    return {"ok": True}


@router.get("/{incident_id}/medic")
async def medic(incident_id: str, request: Request):
    inc = await request.app.state.orchestrator.get_incident(incident_id)
    if inc is None:
        return _NOT_FOUND
    trace = inc.medic if inc.medic is not None else MedicTrace()
    return trace.model_dump(mode="json")


@router.get("/{incident_id}/events")
async def incident_events(incident_id: str, request: Request):
    orch = request.app.state.orchestrator
    inc = await orch.get_incident(incident_id)
    if inc is None:
        return _NOT_FOUND
    hub = request.app.state.hub
    snapshot = incident_to_json(inc)

    async def stream():
        yield sse_frame("incident", snapshot)
        async for frame in hub.subscribe(incident_id):
            yield frame

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
