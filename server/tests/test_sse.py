"""SSE: snapshot on connect, incident events on tear, per-incident channel."""

from __future__ import annotations

import asyncio
import json

from tests.conftest import app_client, fake_backends


async def _read_event(lines) -> tuple[str, dict]:
    """Read one `event:`/`data:` frame, skipping comments and blanks."""
    event = None
    data = None
    async for line in lines:
        if line.startswith(":") or not line.strip():
            if event is not None and data is not None:
                return event, json.loads(data)
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = line[len("data:"):].strip()
            # data is a single line of JSON in our frames; frame ends on blank
    raise AssertionError("stream ended before a full event arrived")


async def _read_until(lines, wanted: str, max_events: int = 50) -> dict:
    for _ in range(max_events):
        event, payload = await _read_event(lines)
        if event == wanted:
            return payload
    raise AssertionError(f"no {wanted!r} event within {max_events} events")


async def test_global_stream_snapshot_and_tear_events():
    async with app_client(backends=fake_backends()) as (client, _app):
        async with client.stream("GET", "/api/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = resp.aiter_lines()

            event, payload = await asyncio.wait_for(_read_event(lines), 5)
            assert event == "state"
            assert payload["live_incident_id"] is None

            r = await client.post(
                "/api/demo/tear", json={"defect": "checkout-null"}
            )
            assert r.status_code == 201
            iid = r.json()["incident_id"]

            incident = await asyncio.wait_for(_read_until(lines, "incident"), 5)
            assert incident["id"] == iid
            assert incident["defect_key"] == "checkout-null"


async def test_incident_stream_snapshot():
    async with app_client(backends=fake_backends()) as (client, _app):
        r = await client.post("/api/demo/tear", json={"defect": "penny-shaver"})
        iid = r.json()["incident_id"]
        async with client.stream("GET", f"/api/incidents/{iid}/events") as resp:
            assert resp.status_code == 200
            lines = resp.aiter_lines()
            event, payload = await asyncio.wait_for(_read_event(lines), 5)
            assert event == "incident"
            assert payload["id"] == iid

        missing = await client.get("/api/incidents/inc-nope/events")
        assert missing.status_code == 404
