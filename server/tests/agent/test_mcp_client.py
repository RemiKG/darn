"""DynatraceMcpClient against httpx.MockTransport replaying REAL captured
gateway shapes: session header on initialize, SSE-framed tool results, the
verified scope-error signatures, transient retries, and session re-init."""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.dynatrace_mcp import (
    DynatraceAuthError,
    DynatraceMcpClient,
    DynatraceMcpError,
    DynatraceScopeError,
)

URL = "https://vzp00000.apps.dynatrace.com/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp"

INIT_RESULT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "dynatrace-mcp", "version": "0.1.0"},
}

# Verbatim text observed live on 2026-06-11 with the under-scoped token:
SCOPE_TEXT = "Tool error: Insufficient permission to access table (events)."


def _rpc_response(request: httpx.Request, result=None, error=None, headers=None, sse=False):
    body = json.loads(request.content)
    msg = {"jsonrpc": "2.0", "id": body.get("id")}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    if sse:
        text = f"event: message\ndata: {json.dumps(msg)}\n\n"
        return httpx.Response(
            200, text=text, headers={"content-type": "text/event-stream", **(headers or {})}
        )
    return httpx.Response(200, json=msg, headers=headers or {})


def _client_with(handler) -> DynatraceMcpClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return DynatraceMcpClient(URL, "dt0s16.TEST", http=http)


@pytest.mark.asyncio
async def test_initialize_captures_session_and_echoes_it():
    seen_sessions: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_sessions.append(request.headers.get("mcp-session-id"))
        assert request.headers["authorization"] == "Bearer dt0s16.TEST"
        assert "text/event-stream" in request.headers["accept"]
        method = body.get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "sess-abc"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return _rpc_response(
                request, result={"tools": [{"name": "execute-dql"}, {"name": "query-problems"}]}
            )
        raise AssertionError(f"unexpected method {method}")

    client = _client_with(handler)
    await client.connect()
    assert client.session_id == "sess-abc"
    assert client.server_info["name"] == "dynatrace-mcp"
    tools = await client.list_tools()
    assert [t["name"] for t in tools] == ["execute-dql", "query-problems"]
    # initialize had no session header; everything after echoed it
    assert seen_sessions[0] is None
    assert all(s == "sess-abc" for s in seen_sessions[1:])
    await client.aclose()


@pytest.mark.asyncio
async def test_sse_framed_tool_result_is_parsed():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            payload = {"records": [{"endpoint.name": "POST /api/checkout", "failures": 41}]}
            result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
            return _rpc_response(request, result=result, sse=True)
        raise AssertionError(method)

    client = _client_with(handler)
    result = await client.call_tool("execute-dql", {"dqlQueryString": "fetch spans | limit 1"})
    assert result.data == {"records": [{"endpoint.name": "POST /api/checkout", "failures": 41}]}
    assert result.seconds >= 0
    await client.aclose()


@pytest.mark.asyncio
async def test_iserror_scope_signature_raises_scope_error_with_exact_message():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            result = {"isError": True, "content": [{"type": "text", "text": SCOPE_TEXT}]}
            return _rpc_response(request, result=result)
        raise AssertionError(method)

    client = _client_with(handler)
    with pytest.raises(DynatraceScopeError) as exc:
        await client.call_tool("query-problems", {"status": "ACTIVE", "history": "30m"})
    assert str(exc.value) == SCOPE_TEXT  # raw message preserved verbatim
    await client.aclose()


@pytest.mark.asyncio
async def test_minus32603_on_grail_tool_becomes_scope_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            calls["n"] += 1
            return _rpc_response(request, error={"code": -32603, "message": "Internal error"})
        raise AssertionError(method)

    transport = httpx.MockTransport(handler)
    client = DynatraceMcpClient(
        URL, "dt0s16.TEST", http=httpx.AsyncClient(transport=transport), retries=0
    )
    with pytest.raises(DynatraceScopeError) as exc:
        await client.call_tool("execute-dql", {"dqlQueryString": "fetch events | limit 1"})
    assert "Internal error" in str(exc.value)
    assert calls["n"] == 1  # retries=0 -> exactly one real attempt
    await client.aclose()


@pytest.mark.asyncio
async def test_transient_5xx_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, text="bad gateway")
            return _rpc_response(
                request, result={"content": [{"type": "text", "text": "{\"problems\": []}"}]}
            )
        raise AssertionError(method)

    client = _client_with(handler)
    result = await client.call_tool("query-problems", {"status": "ACTIVE"})
    assert result.data == {"problems": []}
    assert calls["n"] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_session_expiry_404_triggers_reinit_and_retry():
    state = {"inits": 0, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            state["inits"] += 1
            return _rpc_response(
                request, result=INIT_RESULT, headers={"mcp-session-id": f"sess-{state['inits']}"}
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(404, text="session not found")
            assert request.headers["mcp-session-id"] == "sess-2"
            return _rpc_response(
                request, result={"content": [{"type": "text", "text": "{\"ok\": true}"}]}
            )
        raise AssertionError(method)

    client = _client_with(handler)
    result = await client.call_tool("get-problem-by-id", {"problemId": "P-1"})
    assert result.data == {"ok": True}
    assert state["inits"] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_http_401_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _client_with(handler)
    with pytest.raises(DynatraceAuthError):
        await client.connect()
    await client.aclose()


@pytest.mark.asyncio
async def test_non_scope_tool_error_is_plain_mcp_error():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content).get("method")
        if method == "initialize":
            return _rpc_response(request, result=INIT_RESULT, headers={"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        result = {"isError": True, "content": [{"type": "text", "text": "Tool error: bad DQL syntax"}]}
        return _rpc_response(request, result=result)

    client = _client_with(handler)
    with pytest.raises(DynatraceMcpError) as exc:
        await client.call_tool("execute-dql", {"dqlQueryString": "fetch nope"})
    assert not isinstance(exc.value, DynatraceScopeError)
    await client.aclose()
