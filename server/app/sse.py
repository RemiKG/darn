"""SSE hub — a global bus plus per-incident channels.

Frames are the plain SSE wire format: `event: <name>\\ndata: <json>\\n\\n`,
with a comment heartbeat every 15 seconds so proxies keep the pipe open.
Each subscriber gets its own bounded queue; on overflow the oldest frame is
dropped (the next full-incident publish makes the client whole again).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

HEARTBEAT_SECONDS = 15
QUEUE_SIZE = 256

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_frame(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


class SseHub:
    def __init__(self) -> None:
        self._global: set[asyncio.Queue[tuple[str, str]]] = set()
        self._channels: dict[str, set[asyncio.Queue[tuple[str, str]]]] = {}

    async def publish(
        self,
        event_name: str,
        payload: Any,
        incident_id: Optional[str] = None,
    ) -> None:
        """Deliver to the global bus, and to the incident channel when given."""
        item = (event_name, json.dumps(payload, default=str))
        for q in list(self._global):
            self._offer(q, item)
        if incident_id is not None:
            for q in list(self._channels.get(incident_id, ())):
                self._offer(q, item)

    @staticmethod
    def _offer(q: asyncio.Queue, item: tuple[str, str]) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # drop the oldest frame
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass

    async def subscribe(
        self, incident_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Yield formatted SSE frames until the consumer disconnects."""
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        bucket = (
            self._global
            if incident_id is None
            else self._channels.setdefault(incident_id, set())
        )
        bucket.add(q)
        try:
            while True:
                try:
                    event, data = await asyncio.wait_for(
                        q.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: {event}\ndata: {data}\n\n"
        finally:
            bucket.discard(q)
            if incident_id is not None and not bucket:
                self._channels.pop(incident_id, None)
