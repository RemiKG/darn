"""Caching health service.

Every 30 seconds the HealthSource seam is asked for a fresh HealthCard; the
result is cached (served by /api/health-card and /api/state) and published as
the SSE `health` event. When the source is unavailable the card says so
plainly — numerals stay honest, nothing is fabricated.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.demo.seams import HealthSource, NotConfiguredError
from app.models import HealthCard
from app.sse import SseHub

log = logging.getLogger("darn.health")

REFRESH_SECONDS = 30
UNAVAILABLE_REASON = "telemetry not connected on this deployment"


class HealthService:
    def __init__(self, source: HealthSource, hub: SseHub):
        self._source = source
        self._hub = hub
        self._card = HealthCard(
            status="unavailable", source="unavailable", reason=UNAVAILABLE_REASON
        )
        self._task: Optional[asyncio.Task] = None

    def card(self) -> HealthCard:
        return self._card

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self._refresh()
            await asyncio.sleep(REFRESH_SECONDS)

    async def _refresh(self) -> None:
        try:
            card = await self._source.health_card()
        except asyncio.CancelledError:
            raise
        except NotConfiguredError:
            card = HealthCard(
                status="unavailable", source="unavailable", reason=UNAVAILABLE_REASON
            )
        except Exception as e:
            log.warning("health refresh failed: %s", e)
            card = HealthCard(
                status="unavailable",
                source="unavailable",
                reason="telemetry refresh failed; retrying",
            )
        self._card = card
        await self._hub.publish("health", card.model_dump(mode="json"))
