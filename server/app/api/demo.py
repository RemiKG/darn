"""POST /api/demo/tear — ship one of the four bad commits."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.demo.orchestrator import CooldownError, LockedError, UnknownDefectError
from app.demo.seams import NotConfiguredError
from app.sessions import session_id

router = APIRouter(prefix="/demo")


class TearBody(BaseModel):
    defect: Literal[
        "checkout-null", "catalog-stampede", "penny-shaver", "inventory-grenade"
    ]


@router.post("/tear", status_code=201)
async def tear(body: TearBody, request: Request):
    orch = request.app.state.orchestrator
    try:
        incident = await orch.tear(session_id(request), body.defect)
    except UnknownDefectError:
        return JSONResponse({"error": "unknown_defect"}, status_code=422)
    except LockedError as e:
        return JSONResponse(
            {"error": "locked", "incident_id": e.incident_id}, status_code=409
        )
    except CooldownError as e:
        return JSONResponse({"error": "cooldown", "until": e.until}, status_code=425)
    except NotConfiguredError as e:
        return JSONResponse(
            {"error": "not_configured", "missing": e.missing}, status_code=503
        )
    return {"incident_id": incident.id}
