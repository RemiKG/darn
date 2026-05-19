"""MemoryStore semantics: snapshot reads, receipt union round trips, queries."""

from __future__ import annotations

import time

from app import models
from app.store import DemoState
from app.store.memory import MemoryStore


def _incident(**overrides) -> models.Incident:
    inc = models.Incident(kind="demo", defect_key="checkout-null", title="The checkout null")
    for k, v in overrides.items():
        setattr(inc, k, v)
    return inc


async def test_incident_roundtrip_preserves_receipt_types():
    store = MemoryStore()
    inc = _incident()
    inc.stage("detected").receipts.append(
        models.DavisProblemReceipt(problem_id="P-1", title="Failure rate increase")
    )
    inc.stage("diagnosed").receipts.append(
        models.DqlReceipt(query="fetch spans", group="numbers")
    )
    inc.stage("pr_open").receipts.append(
        models.PrReceipt(repo="r/x", branch="darn/fix-a", number=7)
    )
    await store.put_incident(inc)

    loaded = await store.get_incident(inc.id)
    assert loaded is not None
    assert isinstance(loaded.stage("detected").receipts[0], models.DavisProblemReceipt)
    assert isinstance(loaded.stage("diagnosed").receipts[0], models.DqlReceipt)
    assert isinstance(loaded.stage("pr_open").receipts[0], models.PrReceipt)
    assert loaded.stage("pr_open").receipts[0].number == 7


async def test_reads_are_snapshots():
    store = MemoryStore()
    inc = _incident()
    await store.put_incident(inc)
    a = await store.get_incident(inc.id)
    a.title = "mutated"
    b = await store.get_incident(inc.id)
    assert b.title == "The checkout null"


async def test_get_missing_incident_is_none():
    store = MemoryStore()
    assert await store.get_incident("inc-nope") is None


async def test_summaries_newest_first():
    store = MemoryStore()
    older = _incident(started_at=time.time() - 100)
    older.status = "verified_closed"
    older.ended_at = older.started_at + 60
    newer = _incident(started_at=time.time())
    await store.put_incident(older)
    await store.put_incident(newer)
    summaries = await store.list_incident_summaries()
    assert [s.id for s in summaries] == [newer.id, older.id]
    closed = next(s for s in summaries if s.id == older.id)
    assert closed.detected_to_closed_s == 60


async def test_get_live_incident():
    store = MemoryStore()
    assert await store.get_live_incident() is None
    done = _incident()
    done.status = "verified_closed"
    live = _incident()
    await store.put_incident(done)
    await store.put_incident(live)
    found = await store.get_live_incident()
    assert found is not None and found.id == live.id


async def test_delete_incidents_by_kind():
    store = MemoryStore()
    demo = _incident()
    byo = _incident(kind="byo")
    await store.put_incident(demo)
    await store.put_incident(byo)
    assert await store.delete_incidents("byo") == 1
    assert await store.get_incident(byo.id) is None
    assert await store.get_incident(demo.id) is not None


async def test_demo_state_roundtrip():
    store = MemoryStore()
    fresh = await store.get_demo_state()
    assert fresh.lock.active is False
    assert fresh.cooldown.until is None
    assert fresh.last_mend is None

    fresh.lock.active = True
    fresh.lock.incident_id = "inc-abc"
    fresh.cooldown.until = 123.0
    await store.put_demo_state(fresh)
    loaded = await store.get_demo_state()
    assert isinstance(loaded, DemoState)
    assert loaded.lock.incident_id == "inc-abc"
    assert loaded.cooldown.until == 123.0


async def test_settings_and_byo_roundtrip():
    store = MemoryStore()
    assert await store.get_settings() is None
    await store.put_settings({"poll_seconds": 45})
    assert (await store.get_settings())["poll_seconds"] == 45

    byo = await store.get_byo()
    assert byo.connected is False
    byo.connected = True
    byo.tenant_host = "abc.apps.dynatrace.com"
    byo.mappings.append(models.ServiceMapping(service="svc", repo="o/r"))
    await store.put_byo(byo)
    loaded = await store.get_byo()
    assert loaded.connected is True
    assert loaded.mappings[0].service == "svc"
