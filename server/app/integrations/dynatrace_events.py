"""Dynatrace classic Events API v2 (deployment annotations) + deep-link builders.

The hosted MCP gateway has NO send_event tool (verified 2026-06-11), so
deployment annotations go through the classic Events API:
``POST {DT_CLASSIC_URL}/api/v2/events/ingest`` with an ``Api-Token`` header.
This whole module sits behind the optional ``DT_API_TOKEN`` seam — when the
token is missing the caller skips the send and emits an honest note receipt;
nothing is ever faked.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

import httpx


class DynatraceEventsError(RuntimeError):
    pass


def problem_link(dt_environment: str, problem_id: str) -> str:
    """Deep link to a Davis problem in the tenant UI.

    Confirmed live via ask-dynatrace-docs (2026-06-11): the new Davis problems
    app uses ``{env}/ui/apps/dynatrace.davis.problems/problem/{problemId}``
    where problemId is the LONG internal id (e.g. ``-8491…_1756…V2``).
    Display ids (``P-123456``) only resolve in the classic Problems app, so
    those fall back to the documented classic pattern
    ``{env}/ui/apps/dynatrace.classic.problems/#problems/problemdetails;pid=<id>``.
    """
    env = dt_environment.rstrip("/")
    pid = (problem_id or "").strip()
    if pid.upper().startswith("P-"):
        return f"{env}/ui/apps/dynatrace.classic.problems/#problems/problemdetails;pid={pid}"
    return f"{env}/ui/apps/dynatrace.davis.problems/problem/{pid}"


def trace_link(dt_environment: str, trace_id: str) -> str:
    """Deep link to a distributed trace in the tenant UI.

    Best documented pattern for the Distributed Tracing app:
    ``{env}/ui/apps/dynatrace.distributedtracing/explorer?traceId=<id>`` —
    noted as a best-effort format; the medic drawer treats it as a link, not
    a claim.
    """
    env = dt_environment.rstrip("/")
    return f"{env}/ui/apps/dynatrace.distributedtracing/explorer?traceId={trace_id}"


class DynatraceEvents:
    """Deployment-annotation sender. ``enabled`` is the seam: when False the
    pipeline records an honest skip instead of sending."""

    def __init__(
        self,
        classic_url: str,
        api_token: str,
        *,
        http: Optional[httpx.AsyncClient] = None,
        on_call: Optional[Callable[..., None]] = None,
        timeout: float = 20.0,
    ):
        self.classic_url = classic_url.rstrip("/")
        self._api_token = api_token
        self._own_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._on_call = on_call

    @property
    def enabled(self) -> bool:
        return bool(self.classic_url and self._api_token)

    async def send_deployment(
        self,
        title: str,
        *,
        service_name: str = "",
        entity_selector: str = "",
        properties: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """POST a CUSTOM_DEPLOYMENT event. Raises when not enabled — callers
        must check ``enabled`` first (the seam keeps honesty explicit)."""
        if not self.enabled:
            raise DynatraceEventsError("Events API not configured (DT_API_TOKEN missing)")
        body: dict[str, Any] = {"eventType": "CUSTOM_DEPLOYMENT", "title": title}
        selector = entity_selector
        if not selector and service_name:
            selector = f'type(SERVICE),entityName.equals("{service_name}")'
        if selector:
            body["entitySelector"] = selector
        if properties:
            body["properties"] = {str(k): str(v) for k, v in properties.items()}
        started = time.monotonic()
        ok = False
        try:
            resp = await self._http.post(
                f"{self.classic_url}/api/v2/events/ingest",
                json=body,
                headers={"Authorization": f"Api-Token {self._api_token}"},
            )
            if resp.status_code >= 400:
                raise DynatraceEventsError(
                    f"Events API HTTP {resp.status_code}: {resp.text[:300]}"
                )
            ok = True
            return resp.json() if resp.content else {}
        finally:
            if self._on_call is not None:
                try:
                    self._on_call("dt events ingest", time.monotonic() - started, ok=ok)
                except Exception:
                    pass

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()
