"""Shared JSON views: the /api/state shape and incident serialization.

Both the REST endpoints and the SSE publishers use these, so the wire shape
is identical everywhere.
"""

from __future__ import annotations

import time
from typing import Any

from app.config import settings
from app.models import Incident
from app.store import Store


def incident_to_json(inc: Incident) -> dict[str, Any]:
    data = inc.model_dump(mode="json")
    # Stage.elapsed_s is a property; model_dump skips it. The contract's data
    # model includes it, so enrich here.
    for stage_model, stage_dict in zip(inc.stages, data["stages"]):
        stage_dict["elapsed_s"] = stage_model.elapsed_s
    return data


async def build_state(store: Store, health: Any) -> dict[str, Any]:
    """The /api/state payload — also published as the SSE `state` event.
    `health` is anything with a .card() returning a HealthCard."""
    ds = await store.get_demo_state()
    summaries = await store.list_incident_summaries()
    byo = await store.get_byo()
    card = health.card()
    now = time.time()
    cooldown_until = (
        ds.cooldown.until
        if ds.cooldown.until is not None and ds.cooldown.until > now
        else None
    )
    return {
        "health": card.model_dump(mode="json"),
        "live_incident_id": ds.lock.incident_id if ds.lock.active else None,
        "cooldown_until": cooldown_until,
        "mended": [
            s.model_dump(mode="json") for s in summaries if s.status != "live"
        ],
        "last_mend": ds.last_mend.model_dump(mode="json") if ds.last_mend else None,
        "byo_configured": byo.connected,
        "dynatrace": {
            "configured": settings.dynatrace_configured,
            "mcp_ok": card.source == "dql",
        },
        "github": {
            "configured": settings.github_configured,
            "mode": settings.github_mode,
        },
        "repo_url": (
            f"https://github.com/{settings.github_repo}"
            if settings.github_repo
            else ""
        ),
        "tenant_url": settings.dt_environment,
    }
