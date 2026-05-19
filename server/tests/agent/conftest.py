"""Shared fixtures for the agent-pipeline tests.

Fakes replay REAL captured response shapes from the 2026-06-11 live probe of
the Dynatrace hosted MCP gateway (initialize/session header, SSE framing, the
scope-error signatures) and standard GitHub REST payloads.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SERVER_DIR = Path(__file__).resolve().parents[2]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import pytest  # noqa: E402

from app.models import Incident, now_s  # noqa: E402


@pytest.fixture
def fake_settings():
    return SimpleNamespace(
        poll_seconds=30,
        dql_budget_per_incident=12,
        demo_service_name="loose-threads-shop",
        shop_url="http://shop.test",
        dt_environment="https://vzp00000.apps.dynatrace.com",
        dt_classic_url="https://vzp00000.live.dynatrace.com",
        dt_api_token="",
        gcp_project="test-project",
        gcp_location="global",
        gemini_model="gemini-3-flash-preview",
        github_repo="remikg/loose-threads",
        otel_enabled=False,
    )


class FakeEmitter:
    """Duck-typed StageEmitter: records everything, stamps the incident's
    stages the way the core orchestrator would."""

    def __init__(self, incident: Incident):
        self.incident = incident
        self.events: list[tuple] = []
        self.medic = None
        self.failure: str | None = None

    def stage_started(self, key: str) -> None:
        stage = self.incident.stage(key)
        stage.state = "active"
        stage.started_at = now_s()
        self.events.append(("started", key))

    def stage_done(self, key: str) -> None:
        stage = self.incident.stage(key)
        stage.state = "done"
        stage.done_at = now_s()
        self.events.append(("done", key))

    def emit_receipt(self, key: str, receipt) -> None:
        self.incident.stage(key).receipts.append(receipt)
        self.events.append(("receipt", key, receipt.type))

    def set_medic(self, trace) -> None:
        self.medic = trace

    def fail(self, reason: str) -> None:
        self.failure = reason
        self.events.append(("fail", reason))

    # helpers ---------------------------------------------------------------

    def receipt_types(self, key: str) -> list[str]:
        return [r.type for r in self.incident.stage(key).receipts]


@pytest.fixture
def make_incident():
    def _make(**overrides) -> Incident:
        defaults = dict(
            kind="demo",
            defect_key="checkout-null",
            title="The checkout null",
            service_name="loose-threads-shop",
            repo="remikg/loose-threads",
            sabotage_sha="9b1f2e3aa0d4c5b6e7f8091a2b3c4d5e6f708192",
        )
        defaults.update(overrides)
        return Incident(**defaults)

    return _make


@pytest.fixture
def fake_emitter_factory():
    return FakeEmitter
