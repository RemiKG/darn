"""Streamable-HTTP JSON-RPC client for the Dynatrace hosted MCP gateway.

Verified live against the real gateway (2026-06-11):
- POST {DT_ENVIRONMENT}/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp
  with ``Authorization: Bearer <platform token>`` and
  ``Accept: application/json, text/event-stream``.
- Responses may be plain JSON **or** SSE-framed (``data:`` lines) — both handled.
- The ``initialize`` response carries an ``mcp-session-id`` header which must be
  echoed on every later call; protocolVersion "2025-06-18" works.
- Scope reality today: ``query-problems`` returns ``result.isError`` with content
  text "Tool error: Insufficient permission to access table (events)." and
  ``execute-dql`` returns JSON-RPC error -32603 when the platform token lacks
  Grail read scopes. Both surface here as :class:`DynatraceScopeError` with the
  raw gateway message preserved, so the pipeline can degrade honestly and start
  working the moment a properly-scoped token lands in the environment.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

PROTOCOL_VERSION = "2025-06-18"

# Tool names that read Grail tables; a persistent -32603 from these is the
# observed signature of missing storage read scopes on the platform token.
GRAIL_READ_TOOLS = frozenset(
    {
        "execute-dql",
        "query-problems",
        "get-problem-by-id",
        "get-entity-id",
        "get-entity-name",
        "get-vulnerabilities",
        "get-events-for-kubernetes-cluster",
    }
)

_SCOPE_SIGNATURES = (
    "insufficient permission",
    "permission to access table",
    "missing scope",
    "lacks the required scope",
    "is not allowed to access",
    "permission denied",
    "insufficient scope",
)


def _looks_scope_shaped(text: str) -> bool:
    low = (text or "").lower()
    return any(sig in low for sig in _SCOPE_SIGNATURES)


class DynatraceMcpError(RuntimeError):
    """Any failure talking to the MCP gateway. ``raw`` keeps the gateway payload."""

    def __init__(self, message: str, *, code: Optional[int] = None, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.raw = raw


class DynatraceAuthError(DynatraceMcpError):
    """401/403 at the HTTP layer — the token itself was rejected by the gateway."""


class DynatraceScopeError(DynatraceMcpError):
    """The token reached the gateway but lacks Grail read scopes.

    ``str(err)`` is the raw gateway message, verbatim — it is shown to humans,
    never rephrased.
    """


class _SessionExpired(Exception):
    pass


class _Transient(Exception):
    def __init__(self, message: str, *, code: Optional[int] = None, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.raw = raw


@dataclass
class ToolResult:
    """Parsed result of one MCP tool call. ``data`` is JSON-parsed text content
    when possible (or ``structuredContent`` when the server provides it)."""

    name: str
    arguments: dict[str, Any]
    data: Any
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0


def _parse_sse(body: str) -> list[Any]:
    """Parse an SSE-framed body into the JSON payloads of its data lines."""
    messages: list[Any] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        data_lines = [ln[5:].lstrip() for ln in block.split("\n") if ln.startswith("data:")]
        if not data_lines:
            continue
        try:
            messages.append(json.loads("".join(data_lines)))
        except (ValueError, TypeError):
            continue
    return messages


def _pick_message(body: str, want_id: Any) -> dict[str, Any]:
    """Return the JSON-RPC message for ``want_id`` from a JSON or SSE body."""
    stripped = body.lstrip()
    if stripped.startswith("event:") or stripped.startswith("data:") or stripped.startswith(":"):
        candidates = _parse_sse(body)
    else:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            raise DynatraceMcpError(f"Unparseable MCP response body: {body[:200]!r}")
        candidates = parsed if isinstance(parsed, list) else [parsed]
    chosen: Optional[dict[str, Any]] = None
    for msg in candidates:
        if not isinstance(msg, dict):
            continue
        if msg.get("id") == want_id:
            return msg
        if "result" in msg or "error" in msg:
            chosen = msg
    if chosen is None:
        raise DynatraceMcpError(f"No JSON-RPC response found in MCP body: {body[:200]!r}")
    return chosen


def _content_text(result: dict[str, Any]) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts)


def _parse_content(result: dict[str, Any]) -> tuple[Any, str]:
    text = _content_text(result)
    if result.get("structuredContent") is not None:
        return result["structuredContent"], text
    parsed: list[Any] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            raw = item.get("text") or ""
            try:
                parsed.append(json.loads(raw))
            except (ValueError, TypeError):
                parsed.append(raw)
    if not parsed:
        return None, text
    data = parsed[0] if len(parsed) == 1 else parsed
    return data, text


class DynatraceMcpClient:
    """Async client for the hosted gateway. Reusable for BYO tenants — just
    construct with that tenant's ``base_url`` and ``token``.

    ``on_call(name, seconds, ok=..., tokens_in=None, tokens_out=None)`` is the
    medic hook; it fires for every tool call with measured wall time.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 60.0,
        http: Optional[httpx.AsyncClient] = None,
        on_call: Optional[Callable[..., None]] = None,
        client_name: str = "darn-agent",
        client_version: str = "0.1.0",
        retries: int = 2,
    ):
        self.base_url = base_url
        self._token = token
        self._own_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._on_call = on_call
        self._client_name = client_name
        self._client_version = client_version
        self._retries = max(0, retries)
        self._session_id: Optional[str] = None
        # NOTE (verified live 2026-06-11): this gateway may answer initialize
        # WITHOUT an mcp-session-id header (stateless mode), so "connected" is
        # tracked explicitly rather than inferred from the session id.
        self._connected = False
        self._next_id = 1
        self._connect_lock = asyncio.Lock()
        self.server_info: dict[str, Any] = {}

    # ------------------------------------------------------------------ http

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    async def _rpc(self, method: str, params: Optional[dict] = None, *, notify: bool = False) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self._next_id
            self._next_id += 1
            body["params"] = params or {}
        elif params:
            body["params"] = params
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        try:
            resp = await self._http.post(self.base_url, content=json.dumps(body), headers=headers)
        except httpx.HTTPError as e:
            raise _Transient(f"HTTP transport error: {e}") from e
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        if resp.status_code in (401, 403):
            raise DynatraceAuthError(
                f"MCP gateway rejected the token (HTTP {resp.status_code})",
                code=resp.status_code,
                raw=resp.text[:500],
            )
        if resp.status_code == 404 and method != "initialize":
            # Gateway forgot/expired the session — re-initialize and retry.
            raise _SessionExpired()
        if resp.status_code >= 500:
            raise _Transient(f"MCP gateway HTTP {resp.status_code}", raw=resp.text[:500])
        if resp.status_code >= 400:
            raise DynatraceMcpError(
                f"MCP gateway HTTP {resp.status_code}: {resp.text[:300]}",
                code=resp.status_code,
                raw=resp.text[:500],
            )
        if notify:
            return None
        msg = _pick_message(resp.text, body["id"])
        if "error" in msg:
            err = msg["error"] or {}
            emsg = str(err.get("message", "")) or "MCP error"
            code = err.get("code")
            if _looks_scope_shaped(emsg):
                raise DynatraceScopeError(emsg, code=code, raw=err)
            if code == -32603:
                raise _Transient(emsg, code=code, raw=err)
            raise DynatraceMcpError(emsg, code=code, raw=err)
        return msg.get("result", {})

    async def _rpc_with_retry(
        self, method: str, params: Optional[dict] = None, *, tool: Optional[str] = None
    ) -> Any:
        delay = 0.5
        attempt = 0
        while True:
            try:
                return await self._rpc(method, params)
            except _SessionExpired:
                if attempt >= self._retries:
                    raise DynatraceMcpError("MCP session expired and could not be re-established")
                self._session_id = None
                self._connected = False
                await self.connect()
            except _Transient as t:
                if attempt >= self._retries:
                    if t.code == -32603 and tool in GRAIL_READ_TOOLS:
                        # Verified live signature: execute-dql answers -32603 when
                        # the token lacks Grail read scopes. Preserve raw message.
                        raise DynatraceScopeError(str(t), code=t.code, raw=t.raw) from t
                    raise DynatraceMcpError(str(t), code=t.code, raw=t.raw) from t
                await asyncio.sleep(delay)
                delay *= 2
            attempt += 1

    # ----------------------------------------------------------------- public

    async def connect(self) -> dict[str, Any]:
        """initialize + notifications/initialized. Stores the session id."""
        async with self._connect_lock:
            self._session_id = None
            self._connected = False
            try:
                result = await self._rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": self._client_name, "version": self._client_version},
                    },
                )
            except _Transient as t:
                # _Transient is internal retry plumbing; it must never escape
                # the client (callers handle DynatraceMcpError).
                raise DynatraceMcpError(str(t), code=t.code, raw=t.raw) from t
            try:
                await self._rpc("notifications/initialized", notify=True)
            except (_Transient, _SessionExpired):
                # Best-effort once more; gateways tolerate a re-sent notification.
                await asyncio.sleep(0.3)
                try:
                    await self._rpc("notifications/initialized", notify=True)
                except (_Transient, _SessionExpired):
                    pass  # the session may still work; tools/list will tell
            self.server_info = (result or {}).get("serverInfo", {}) if isinstance(result, dict) else {}
            self._connected = True
            return result or {}

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._connected:
            await self.connect()
        result = await self._rpc_with_retry("tools/list", {})
        return (result or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> ToolResult:
        """Call one tool; returns parsed content. Raises DynatraceScopeError on
        the verified scope-failure signatures, DynatraceMcpError otherwise."""
        if not self._connected:
            await self.connect()
        args = arguments or {}
        started = time.monotonic()
        ok = False
        try:
            result = await self._rpc_with_retry(
                "tools/call", {"name": name, "arguments": args}, tool=name
            )
            if isinstance(result, dict) and result.get("isError"):
                text = _content_text(result)
                if _looks_scope_shaped(text):
                    raise DynatraceScopeError(text, raw=result)
                raise DynatraceMcpError(text or f"Tool {name} returned an error", raw=result)
            data, text = _parse_content(result if isinstance(result, dict) else {})
            ok = True
            return ToolResult(
                name=name,
                arguments=args,
                data=data,
                text=text,
                raw=result if isinstance(result, dict) else {"result": result},
                seconds=time.monotonic() - started,
            )
        finally:
            seconds = time.monotonic() - started
            if self._on_call is not None:
                try:
                    self._on_call(name, seconds, ok=ok)
                except Exception:  # the medic must never break the call
                    pass

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()
