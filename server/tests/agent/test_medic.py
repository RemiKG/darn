"""MedicRecorder: aggregation, hook adapters, measured totals, env-priced cost."""

from __future__ import annotations

import pytest

from app.agent.medic import MedicRecorder, MedicRouter
from app.integrations.vertex_gemini import PRICE_IN_ENV, PRICE_OUT_ENV, compute_cost


def test_rows_aggregate_by_tool_and_kind():
    medic = MedicRecorder()
    medic.record("execute-dql", "mcp", 0.8)
    medic.record("execute-dql", "mcp", 1.2)
    medic.record("github compare", "github", 1.1)
    trace = medic.trace()
    dql_row = next(r for r in trace.rows if r.tool == "execute-dql")
    assert dql_row.calls == 2
    assert dql_row.seconds == pytest.approx(2.0)
    assert trace.wall_s == pytest.approx(3.1)


def test_gemini_tokens_accumulate_and_cost_is_none_without_prices(monkeypatch):
    monkeypatch.delenv(PRICE_IN_ENV, raising=False)
    monkeypatch.delenv(PRICE_OUT_ENV, raising=False)
    medic = MedicRecorder()
    medic.record("gemini-3-flash-preview", "gemini", 9.4, tokens_in=18412, tokens_out=1207)
    medic.record("gemini-3-flash-preview", "gemini", 1.0, tokens_in=100, tokens_out=50)
    trace = medic.trace()
    row = trace.rows[0]
    assert row.tokens_in == 18512 and row.tokens_out == 1257
    assert trace.tokens == 18512 + 1257
    assert trace.cost_usd is None  # never invented


def test_cost_computed_from_env_prices(monkeypatch):
    monkeypatch.setenv(PRICE_IN_ENV, "0.50")
    monkeypatch.setenv(PRICE_OUT_ENV, "3.00")
    assert compute_cost(1_000_000, 1_000_000) == pytest.approx(3.50)
    medic = MedicRecorder()
    medic.record("gemini", "gemini", 1.0, tokens_in=2_000_000, tokens_out=500_000)
    assert medic.trace().cost_usd == pytest.approx(2.0 * 0.50 + 0.5 * 3.00)


def test_cost_handles_garbage_prices(monkeypatch):
    monkeypatch.setenv(PRICE_IN_ENV, "cheap")
    monkeypatch.setenv(PRICE_OUT_ENV, "3.00")
    assert compute_cost(1000, 1000) is None


def test_hook_adapter_matches_integration_signature():
    medic = MedicRecorder()
    hook = medic.hook("mcp")
    hook("query-problems", 0.8, ok=True)
    hook("query-problems", 0.4, ok=False)  # failed calls are recorded too
    row = medic.trace().rows[0]
    assert row.tool == "query-problems" and row.kind == "mcp" and row.calls == 2


def test_router_routes_to_current_recorder_and_drops_idle_calls():
    router = MedicRouter()
    hook = router.hook("github")
    hook("github get repo", 0.5)  # no active incident -> dropped
    medic = MedicRecorder()
    router.current = medic
    hook("github get repo", 0.7)
    trace = medic.trace()
    assert len(trace.rows) == 1
    assert trace.rows[0].seconds == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_measure_records_wall_time():
    medic = MedicRecorder()
    async with medic.measure("replay probe", "verify"):
        pass
    trace = medic.trace()
    assert trace.rows[0].tool == "replay probe"
    assert trace.rows[0].kind == "verify"
    assert trace.rows[0].seconds >= 0


def test_trace_url_passthrough():
    medic = MedicRecorder()
    medic.set_trace_url("https://env/ui/apps/dynatrace.distributedtracing/explorer?traceId=abc")
    assert medic.trace().trace_url.endswith("traceId=abc")
