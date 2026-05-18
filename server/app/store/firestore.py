"""Firestore store — Cloud Run deployments.

Collections: incidents (one doc per incident), meta/demo_state, meta/settings,
byo/state. Everything is serialized via model_dump(mode="json").

This module is only imported when STORE resolves to "firestore", so memory-mode
deployments never need google-cloud-firestore loaded.
"""

from __future__ import annotations

import logging
from typing import Optional

from google.cloud import firestore  # imported lazily by app.store.get_store()

from app.config import settings
from app.models import ByoState, Incident, IncidentSummary, summarize
from app.store import DemoState

log = logging.getLogger("darn.store")


def _live_query(col):
    # FieldFilter is the modern API; positional where() is the fallback.
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        return col.where(filter=FieldFilter("status", "==", "live"))
    except ImportError:
        return col.where("status", "==", "live")


def _kind_query(col, kind: str):
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        return col.where(filter=FieldFilter("kind", "==", kind))
    except ImportError:
        return col.where("kind", "==", kind)


class FirestoreStore:
    def __init__(self) -> None:
        self._db = firestore.AsyncClient(
            project=settings.gcp_project or None,
            database=settings.firestore_database,
        )

    async def init(self) -> None:
        return None

    def _incidents(self):
        return self._db.collection("incidents")

    # ------------------------------------------------------------ incidents
    #
    # Firestore rejects arrays nested directly inside arrays, and receipts
    # legitimately contain them (DQL result rows). Incidents are therefore
    # stored as a JSON string payload plus top-level mirror fields for the
    # filters used by queries (status/kind) and sorting (started_at).

    @staticmethod
    def _incident_doc(incident: Incident) -> dict:
        return {
            "id": incident.id,
            "kind": incident.kind,
            "status": incident.status,
            "started_at": incident.started_at,
            "payload": incident.model_dump_json(),
        }

    @staticmethod
    def _incident_from_doc(data: dict) -> Incident:
        payload = data.get("payload")
        if payload:
            return Incident.model_validate_json(payload)
        return Incident.model_validate(data)  # pre-payload docs

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        snap = await self._incidents().document(incident_id).get()
        if not snap.exists:
            return None
        return self._incident_from_doc(snap.to_dict())

    async def put_incident(self, incident: Incident) -> None:
        await self._incidents().document(incident.id).set(self._incident_doc(incident))

    async def list_incident_summaries(self) -> list[IncidentSummary]:
        out: list[IncidentSummary] = []
        async for snap in self._incidents().stream():
            try:
                out.append(summarize(self._incident_from_doc(snap.to_dict())))
            except Exception:
                log.warning("skipping malformed incident doc %s", snap.id)
        out.sort(key=lambda s: s.started_at, reverse=True)
        return out

    async def get_live_incident(self) -> Optional[Incident]:
        live: list[Incident] = []
        async for snap in _live_query(self._incidents()).stream():
            try:
                live.append(self._incident_from_doc(snap.to_dict()))
            except Exception:
                log.warning("skipping malformed live incident doc %s", snap.id)
        if not live:
            return None
        live.sort(key=lambda i: i.started_at, reverse=True)
        return live[0]

    async def delete_incidents(self, kind: str) -> int:
        n = 0
        async for snap in _kind_query(self._incidents(), kind).stream():
            await snap.reference.delete()
            n += 1
        return n

    # ------------------------------------------------------------ demo state

    def _demo_doc(self):
        return self._db.collection("meta").document("demo_state")

    async def get_demo_state(self) -> DemoState:
        snap = await self._demo_doc().get()
        if not snap.exists:
            return DemoState()
        return DemoState.model_validate(snap.to_dict())

    async def put_demo_state(self, state: DemoState) -> None:
        await self._demo_doc().set(state.model_dump(mode="json"))

    # ------------------------------------------------------------ settings

    def _settings_doc(self):
        return self._db.collection("meta").document("settings")

    async def get_settings(self) -> Optional[dict]:
        snap = await self._settings_doc().get()
        return snap.to_dict() if snap.exists else None

    async def put_settings(self, values: dict) -> None:
        await self._settings_doc().set(dict(values))

    # ------------------------------------------------------------ byo

    def _byo_doc(self):
        return self._db.collection("byo").document("state")

    async def get_byo(self) -> ByoState:
        snap = await self._byo_doc().get()
        if not snap.exists:
            return ByoState()
        return ByoState.model_validate(snap.to_dict())

    async def put_byo(self, state: ByoState) -> None:
        await self._byo_doc().set(state.model_dump(mode="json"))
