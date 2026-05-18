"""Bring-your-own tenant: connection validation + the watcher loop skeleton.

The validator implements the ByoValidator seam:
    async validate(tenant_url, token) -> [{name, health}, ...]
    (raises app.demo.seams.ByoValidationError with a calm, design-voiced
    ``hint`` on failure)

The watcher polls the tenant's Davis problems per mapping and hands matches to
an incident factory the core provides — the SAME pipeline then runs with
kind="byo". The demo path is primary; this loop is deliberately modest.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

import httpx

from ..demo.seams import ByoValidationError
from ..integrations.dynatrace_mcp import (
    DynatraceAuthError,
    DynatraceMcpClient,
    DynatraceMcpError,
    DynatraceScopeError,
)

log = logging.getLogger("darn.agent.byo")

MCP_PATH = "/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp"

REGION_HINT = (
    "Couldn't reach the tenant — check the URL region "
    "(apps.dynatrace.com vs live.dynatrace.com)."
)
TOKEN_HINT = (
    "The tenant answered but rejected the token. Mint a platform token with "
    "exactly these scopes: app-engine:apps:run · storage:buckets:read · "
    "storage:logs:read · storage:metrics:read · storage:spans:read · "
    "davis:problems:read · openpipeline:events.ingest — and nothing else."
)
SCOPE_HINT = (
    "Connected, but the token can't read Grail. Add the storage read scopes "
    "(storage:buckets:read, storage:spans:read, storage:logs:read, "
    "storage:metrics:read, storage:events:read) and try again."
)


def mcp_url_for(tenant_url: str) -> str:
    return tenant_url.rstrip("/") + MCP_PATH


def _extract_service_names(payload: Any) -> list[str]:
    """Names out of a get-entity-id result, shape-tolerant."""
    names: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("name") or node.get("entityName") or node.get("displayName")
            if isinstance(name, str) and name:
                names.append(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    walk(payload)
    seen: set[str] = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


class McpByoValidator:
    """Validates a pasted tenant URL + platform token with a fresh MCP client
    (initialize + tools/list, then a best-effort service listing)."""

    def __init__(self, client_factory: Callable[..., DynatraceMcpClient] = DynatraceMcpClient):
        self._client_factory = client_factory

    async def validate(self, tenant_url: str, token: str) -> list[dict[str, str]]:
        tenant = (tenant_url or "").strip().rstrip("/")
        if not tenant.startswith("http"):
            tenant = f"https://{tenant}"
        if not token:
            raise ByoValidationError("No token provided", hint="Paste a platform token (dt0s16…).")
        client = self._client_factory(mcp_url_for(tenant), token, client_name="darn-byo-validate")
        try:
            await client.connect()
            tools = await client.list_tools()
            if not tools:
                raise ByoValidationError(
                    "The MCP gateway listed no tools", hint=REGION_HINT
                )
            services: list[dict[str, str]] = []
            try:
                result = await client.call_tool(
                    "get-entity-id",
                    {"entityType": "dt.entity.service", "entityNameFilter": ""},
                )
                services = [
                    {"name": name, "health": "unknown"}
                    for name in _extract_service_names(result.data or result.text)[:25]
                ]
            except DynatraceScopeError as e:
                raise ByoValidationError(str(e), hint=SCOPE_HINT) from e
            except DynatraceMcpError:
                services = []  # gateway reachable; listing is best-effort
            return services
        except ByoValidationError:
            raise
        except DynatraceAuthError as e:
            raise ByoValidationError(str(e), hint=TOKEN_HINT) from e
        except (DynatraceMcpError, httpx.HTTPError) as e:
            raise ByoValidationError(str(e), hint=REGION_HINT) from e
        finally:
            await client.aclose()


class ByoWatcher:
    """Polls query-problems for each watched mapping; spawns incidents through
    the core-provided factory. One task, cancel-safe, dedupes problem ids."""

    def __init__(
        self,
        *,
        client: DynatraceMcpClient,
        mappings_provider: Callable[[], Awaitable[list[dict[str, Any]]]],
        incident_factory: Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]],
        poll_seconds: int = 30,
    ):
        self._client = client
        self._mappings_provider = mappings_provider
        self._incident_factory = incident_factory
        self._poll_seconds = max(10, poll_seconds)
        self._seen_problem_ids: set[str] = set()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="darn-byo-watcher")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        from .stages import _extract_problems, _problem_id  # shape-tolerant parsers

        while True:
            try:
                mappings = [
                    m
                    for m in await self._mappings_provider()
                    if m.get("watch") and not m.get("paused")
                ]
                if mappings:
                    result = await self._client.call_tool(
                        "query-problems", {"status": "ACTIVE", "history": "30m"}
                    )
                    problems = _extract_problems(result.data or result.text)
                    for problem in problems:
                        pid = _problem_id(problem)
                        if not pid or pid in self._seen_problem_ids:
                            continue
                        blob = json.dumps(problem)
                        for mapping in mappings:
                            service = str(mapping.get("service", ""))
                            if service and service in blob:
                                self._seen_problem_ids.add(pid)
                                await self._incident_factory(mapping, problem)
                                break
            except asyncio.CancelledError:
                raise
            except DynatraceScopeError as e:
                log.warning("byo watcher: scope error (will retry): %s", e)
            except Exception as e:  # noqa: BLE001 — the watcher must outlive hiccups
                log.warning("byo watcher: %s", e)
            await asyncio.sleep(self._poll_seconds)
