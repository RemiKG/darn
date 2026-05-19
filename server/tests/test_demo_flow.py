"""Full incident lifecycles driven by fake seams: approve, decline, timeout,
lock/cooldown/409/425, needle lapse + pickup."""

from __future__ import annotations

import asyncio

from app.config import settings
from tests.conftest import (
    app_client,
    fake_backends,
    second_client,
    stage_state,
    wait_for,
)


async def _get_incident(client, incident_id: str) -> dict:
    r = await client.get(f"/api/incidents/{incident_id}")
    assert r.status_code == 200
    return r.json()


async def test_full_mend_flow(monkeypatch):
    backends = fake_backends()
    async with app_client(backends=backends) as (client, app):
        r = await client.post("/api/demo/tear", json={"defect": "checkout-null"})
        assert r.status_code == 201
        iid = r.json()["incident_id"]

        # lock engaged: a second tear is refused
        r2 = await client.post("/api/demo/tear", json={"defect": "penny-shaver"})
        assert r2.status_code == 409
        assert r2.json() == {"error": "locked", "incident_id": iid}

        # the pipeline runs to PR-open
        inc = await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: stage_state(i, "pr_open") == "done",
        )
        assert inc["status"] == "live"
        assert inc["pr_number"] == 48
        assert inc["problem_id"] == "P-25061123"
        assert stage_state(inc, "detected") == "done"
        assert stage_state(inc, "diagnosed") == "done"
        assert stage_state(inc, "fix_written") == "done"
        assert inc["sabotage_sha"] == "9b1f2e7c0ffee"
        # receipts landed where they belong
        detected = next(s for s in inc["stages"] if s["key"] == "detected")
        assert any(rc["type"] == "davis_problem" for rc in detected["receipts"])

        # a stranger cannot approve
        stranger = second_client(app)
        try:
            r3 = await stranger.post(f"/api/incidents/{iid}/approve")
            assert r3.status_code == 403
            assert r3.json()["error"] == "not_holder"
        finally:
            await stranger.aclose()

        # the needle-holder approves
        r4 = await client.post(f"/api/incidents/{iid}/approve")
        assert r4.status_code == 200

        inc = await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: i["status"] == "verified_closed",
        )
        assert stage_state(inc, "approved") == "done"
        assert stage_state(inc, "verified") == "done"
        assert backends.sabotage.merged == [iid]
        summary = inc["wall_clock_summary"]
        assert summary is not None
        assert summary["dql_receipts"] == 1
        assert summary["token_cost_usd"] == 0.0381

        # medic endpoint serves the trace
        rm = await client.get(f"/api/incidents/{iid}/medic")
        assert rm.status_code == 200
        assert rm.json()["tokens"] == 19_619

        # global state: lock released, cooldown live, mended strip + last mend
        rs = await client.get("/api/state")
        state = rs.json()
        assert state["live_incident_id"] is None
        assert state["cooldown_until"] is not None
        assert state["last_mend"]["id"] == iid
        assert [m["id"] for m in state["mended"]] == [iid]

        # cooldown: the next tear must wait
        r5 = await client.post("/api/demo/tear", json={"defect": "penny-shaver"})
        assert r5.status_code == 425
        assert r5.json()["error"] == "cooldown"
        assert r5.json()["until"] == state["cooldown_until"]


async def test_approve_before_pr_open_is_wrong_stage():
    gate = asyncio.Event()
    async with app_client(backends=fake_backends(hold_diagnose=gate)) as (
        client,
        _app,
    ):
        r = await client.post("/api/demo/tear", json={"defect": "catalog-stampede"})
        iid = r.json()["incident_id"]
        await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: stage_state(i, "detected") == "done",
        )
        r2 = await client.post(f"/api/incidents/{iid}/approve")
        assert r2.status_code == 409
        assert r2.json()["error"] == "wrong_stage"
        r3 = await client.post(f"/api/incidents/{iid}/decline")
        assert r3.status_code == 409
        gate.set()


async def test_decline_reverts_and_tidies():
    backends = fake_backends()
    async with app_client(backends=backends) as (client, app):
        r = await client.post("/api/demo/tear", json={"defect": "penny-shaver"})
        iid = r.json()["incident_id"]
        await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: stage_state(i, "pr_open") == "done",
        )

        # a stranger cannot decline either
        stranger = second_client(app)
        try:
            r2 = await stranger.post(f"/api/incidents/{iid}/decline")
            assert r2.status_code == 403
        finally:
            await stranger.aclose()

        r3 = await client.post(f"/api/incidents/{iid}/decline")
        assert r3.status_code == 200
        inc = await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: i["status"] == "declined_reverted",
        )
        assert stage_state(inc, "approved") == "tied_off"
        assert stage_state(inc, "verified") == "skipped"
        assert backends.sabotage.closed == [iid]
        assert backends.sabotage.reverted == [iid]
        # lock released, cooldown running
        state = (await client.get("/api/state")).json()
        assert state["live_incident_id"] is None
        assert state["cooldown_until"] is not None
        # declined runs do not become "last mend"
        assert state["last_mend"] is None


async def test_approve_timeout_auto_declines(monkeypatch):
    monkeypatch.setattr(settings, "approve_timeout_seconds", 0)
    backends = fake_backends()
    async with app_client(backends=backends) as (client, _app):
        r = await client.post("/api/demo/tear", json={"defect": "inventory-grenade"})
        iid = r.json()["incident_id"]
        inc = await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: i["status"] == "declined_timeout",
        )
        assert stage_state(inc, "approved") == "tied_off"
        assert backends.sabotage.closed == [iid]
        assert backends.sabotage.reverted == [iid]


async def test_needle_lapse_and_pickup(monkeypatch):
    async with app_client(backends=fake_backends()) as (client, app):
        r = await client.post("/api/demo/tear", json={"defect": "checkout-null"})
        iid = r.json()["incident_id"]
        await wait_for(
            lambda: _get_incident(client, iid),
            lambda i: stage_state(i, "pr_open") == "done",
        )

        spectator = second_client(app)
        try:
            # while the holder is fresh, the spectator may not pick up
            p1 = (await spectator.post(f"/api/incidents/{iid}/presence")).json()
            assert p1["holder"] is False
            assert p1["can_pickup"] is False
            assert p1["watching"] >= 1
            pk0 = await spectator.post(f"/api/incidents/{iid}/pickup")
            assert pk0.status_code == 409

            # the holder lapses
            monkeypatch.setattr(settings, "needle_lapse_seconds", 0)
            await asyncio.sleep(0.01)
            p2 = (await spectator.post(f"/api/incidents/{iid}/presence")).json()
            assert p2["can_pickup"] is True

            pk = await spectator.post(f"/api/incidents/{iid}/pickup")
            assert pk.status_code == 200
            assert pk.json() == {"holder": True}

            # the new holder may approve; the old one may not
            monkeypatch.setattr(settings, "needle_lapse_seconds", 90)
            await spectator.post(f"/api/incidents/{iid}/presence")
            old = await client.post(f"/api/incidents/{iid}/approve")
            assert old.status_code == 403
            new = await spectator.post(f"/api/incidents/{iid}/approve")
            assert new.status_code == 200
            await wait_for(
                lambda: _get_incident(client, iid),
                lambda i: i["status"] == "verified_closed",
            )
        finally:
            await spectator.aclose()


async def test_presence_counts_watchers():
    async with app_client(backends=fake_backends()) as (client, app):
        r = await client.post("/api/demo/tear", json={"defect": "checkout-null"})
        iid = r.json()["incident_id"]
        p1 = (await client.post(f"/api/incidents/{iid}/presence")).json()
        assert p1["holder"] is True
        assert p1["watching"] == 1
        other = second_client(app)
        try:
            p2 = (await other.post(f"/api/incidents/{iid}/presence")).json()
            assert p2["watching"] == 2
            assert p2["holder"] is False
            assert p2["holder_label"] == "the needle-holder"
        finally:
            await other.aclose()
