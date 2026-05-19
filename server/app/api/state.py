"""GET /api/state, /api/health-card, and the global SSE stream."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.sse import SSE_HEADERS, sse_frame

router = APIRouter()


@router.get("/state")
async def get_state(request: Request):
    return await request.app.state.state_view()


@router.get("/health-card")
async def get_health_card(request: Request):
    return request.app.state.health.card().model_dump(mode="json")


@router.get("/events")
async def global_events(request: Request):
    hub = request.app.state.hub
    snapshot = await request.app.state.state_view()

    async def stream():
        yield sse_frame("state", snapshot)
        async for frame in hub.subscribe():
            yield frame

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
