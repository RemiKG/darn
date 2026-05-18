"""Store protocol + factory.

One async store interface, two backends: in-memory (dev/tests) and Firestore
(Cloud Run). The Firestore module is imported lazily so STORE=memory never
loads GCP libraries.

Single-process writer semantics: the orchestrator owns the live incident and
writes through; reads return parsed copies (snapshot semantics, like Firestore).
"""

from __future__ import annotations

from typing import Optional, Protocol

from pydantic import BaseModel, Field

from app.config import settings
from app.models import ByoState, Incident, IncidentSummary


# ------------------------------------------------------------- demo state
# DemoState lives here (not models.py, which is the shared/frozen
# model module): lock {active, incident_id}, cooldown {until}, last_mend.

class DemoLock(BaseModel):
    active: bool = False
    incident_id: Optional[str] = None


class DemoCooldown(BaseModel):
    until: Optional[float] = None


class DemoState(BaseModel):
    lock: DemoLock = Field(default_factory=DemoLock)
    cooldown: DemoCooldown = Field(default_factory=DemoCooldown)
    last_mend: Optional[IncidentSummary] = None


# ------------------------------------------------------------- protocol

class Store(Protocol):
    async def init(self) -> None: ...

    # incidents
    async def get_incident(self, incident_id: str) -> Optional[Incident]: ...
    async def put_incident(self, incident: Incident) -> None: ...
    async def list_incident_summaries(self) -> list[IncidentSummary]: ...
    async def get_live_incident(self) -> Optional[Incident]: ...
    async def delete_incidents(self, kind: str) -> int: ...

    # demo state
    async def get_demo_state(self) -> DemoState: ...
    async def put_demo_state(self, state: DemoState) -> None: ...

    # user settings (the /api/settings document, stored as a plain dict)
    async def get_settings(self) -> Optional[dict]: ...
    async def put_settings(self, values: dict) -> None: ...

    # BYO state (secret VALUES never live here — only in the secret backend;
    # the secret name is derived from tenant_host, see app.secrets)
    async def get_byo(self) -> ByoState: ...
    async def put_byo(self, state: ByoState) -> None: ...


def get_store() -> Store:
    if settings.store_mode == "firestore":
        from app.store.firestore import FirestoreStore  # lazy: needs GCP libs

        return FirestoreStore()
    from app.store.memory import MemoryStore

    return MemoryStore()
