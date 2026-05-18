"""In-memory store — dev and tests.

Documents are kept as JSON-able dicts (the same shape Firestore would hold),
so reads return fresh parsed models: snapshot semantics, no shared mutable
state with callers.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models import ByoState, Incident, IncidentSummary, summarize
from app.store import DemoState

log = logging.getLogger("darn.store")


class MemoryStore:
    def __init__(self) -> None:
        self._incidents: dict[str, dict] = {}
        self._demo_state: Optional[dict] = None
        self._settings: Optional[dict] = None
        self._byo: Optional[dict] = None

    async def init(self) -> None:
        return None

    # ------------------------------------------------------------ incidents

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        data = self._incidents.get(incident_id)
        return Incident.model_validate(data) if data is not None else None

    async def put_incident(self, incident: Incident) -> None:
        self._incidents[incident.id] = incident.model_dump(mode="json")

    async def list_incident_summaries(self) -> list[IncidentSummary]:
        out: list[IncidentSummary] = []
        for data in self._incidents.values():
            try:
                out.append(summarize(Incident.model_validate(data)))
            except Exception:  # tolerate a malformed doc rather than dying
                log.warning("skipping malformed incident doc")
        out.sort(key=lambda s: s.started_at, reverse=True)
        return out

    async def get_live_incident(self) -> Optional[Incident]:
        live = [d for d in self._incidents.values() if d.get("status") == "live"]
        if not live:
            return None
        live.sort(key=lambda d: d.get("started_at") or 0, reverse=True)
        return Incident.model_validate(live[0])

    async def delete_incidents(self, kind: str) -> int:
        doomed = [i for i, d in self._incidents.items() if d.get("kind") == kind]
        for i in doomed:
            del self._incidents[i]
        return len(doomed)

    # ------------------------------------------------------------ demo state

    async def get_demo_state(self) -> DemoState:
        if self._demo_state is None:
            return DemoState()
        return DemoState.model_validate(self._demo_state)

    async def put_demo_state(self, state: DemoState) -> None:
        self._demo_state = state.model_dump(mode="json")

    # ------------------------------------------------------------ settings

    async def get_settings(self) -> Optional[dict]:
        return dict(self._settings) if self._settings is not None else None

    async def put_settings(self, values: dict) -> None:
        self._settings = dict(values)

    # ------------------------------------------------------------ byo

    async def get_byo(self) -> ByoState:
        if self._byo is None:
            return ByoState()
        return ByoState.model_validate(self._byo)

    async def put_byo(self, state: ByoState) -> None:
        self._byo = state.model_dump(mode="json")
