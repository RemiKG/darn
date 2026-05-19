"""Honest NotConfigured fallbacks.

These run when the agent layer is absent or fails to wire. They never fake:
sabotage refuses with the exact missing env vars, health says plainly that
telemetry is not connected, the pipeline never advances a stage (it cannot be
reached anyway — the tear endpoint already refused).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings
from app.models import HealthCard, Incident
from app.demo.seams import (
    Backends,
    NotConfiguredError,
    StageEmitter,
)

log = logging.getLogger("darn.demo")

UNAVAILABLE_REASON = "telemetry not connected on this deployment"


def demo_missing() -> list[str]:
    missing: list[str] = []
    if not settings.github_repo:
        missing.append("GITHUB_REPO")
    if settings.github_mode == "none":
        missing.append("GITHUB_TOKEN or GITHUB_APP_*")
    if not settings.dt_environment:
        missing.append("DT_ENVIRONMENT")
    if not settings.dt_platform_token:
        missing.append("DT_PLATFORM_TOKEN")
    return missing or ["agent wiring"]


class NotConfiguredSabotage:
    async def commit_defect(self, defect_key: str) -> dict[str, Any]:
        raise NotConfiguredError(demo_missing())

    async def revert(self, incident: Incident) -> str:
        raise NotConfiguredError(demo_missing())

    async def merge_pr(self, incident: Incident) -> None:
        raise NotConfiguredError(demo_missing())

    async def close_pr(self, incident: Incident) -> None:
        raise NotConfiguredError(demo_missing())


class IdlePipeline:
    """Never advances a stage. With NotConfiguredSabotage in front of it, the
    tear endpoint already refused, so these should never actually run."""

    async def run_detect(self, incident: Incident, emitter: StageEmitter) -> None:
        log.warning("IdlePipeline.run_detect reached — agent layer not wired")

    async def run_diagnose_fix_pr(
        self, incident: Incident, emitter: StageEmitter
    ) -> None:
        log.warning("IdlePipeline.run_diagnose_fix_pr reached — agent layer not wired")

    async def run_verify(self, incident: Incident, emitter: StageEmitter) -> None:
        log.warning("IdlePipeline.run_verify reached — agent layer not wired")


class UnavailableHealth:
    async def health_card(self) -> HealthCard:
        return HealthCard(
            status="unavailable", source="unavailable", reason=UNAVAILABLE_REASON
        )


class NotConfiguredByoValidator:
    async def validate(
        self, tenant_url: str, platform_token: str
    ) -> list[dict[str, str]]:
        raise NotConfiguredError(["MCP validator (agent layer not wired)"])

    async def github_install_url(self) -> Optional[str]:
        return None


def fallback_backends() -> Backends:
    return Backends(
        sabotage=NotConfiguredSabotage(),
        pipeline=IdlePipeline(),
        health=UnavailableHealth(),
        byo_validator=NotConfiguredByoValidator(),
    )
