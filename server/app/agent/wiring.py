"""Composition root for the agent pipeline — the seam the core server calls.

    from app.agent.wiring import build_backends
    backends = build_backends()           # uses app.config.settings
    backends["pipeline"].run_detect(...)  # AgentPipeline
    backends["sabotage"].commit_defect(.) # SabotageBackend
    backends["health"].health_card()      # HealthSource
    backends["byo_validator"].validate(.) # ByoValidator

Exact signature:

    def build_backends(settings_obj: Any = None, **kwargs: Any) -> dict[str, Any]

``settings_obj`` defaults to ``app.config.settings``. ``**kwargs`` tolerates
anything the core passes; recognised overrides (all optional, mainly for
tests): ``mcp``, ``github``, ``gemini``, ``events``, ``telemetry``,
``diagnosis_runner``, ``http``. Unknown kwargs are ignored.

Backends degrade honestly when their env vars are missing: the health card
says "not configured", the pipeline fails a stage with a plain reason, and the
sabotage backend is None when GitHub is unconfigured (the API layer answers
503 not_configured).
"""

from __future__ import annotations

from typing import Any, Optional

from ..integrations.dynatrace_events import DynatraceEvents
from ..integrations.dynatrace_mcp import DynatraceMcpClient
from ..integrations.github_client import GitHubClient
from ..integrations.vertex_gemini import VertexGemini
from .byo import McpByoValidator
from .health import DqlHealthSource
from .medic import MedicRouter
from .otel import build_telemetry
from .sabotage import GitHubSabotage
from .stages import DarnPipeline


def build_backends(settings_obj: Any = None, **kwargs: Any) -> dict[str, Any]:
    if settings_obj is None:
        from ..config import settings as settings_obj  # type: ignore[no-redef]
    s = settings_obj

    telemetry = kwargs.get("telemetry")
    if telemetry is None:
        telemetry = build_telemetry(s)

    router = MedicRouter()

    mcp: Optional[DynatraceMcpClient] = kwargs.get("mcp")
    if mcp is None and getattr(s, "dynatrace_configured", False):
        mcp = DynatraceMcpClient(
            s.dt_mcp_url, s.dt_platform_token, on_call=router.hook("mcp")
        )

    github: Optional[GitHubClient] = kwargs.get("github")
    if github is None and getattr(s, "github_configured", False):
        github = GitHubClient(
            s.github_repo,
            token=s.github_token,
            app_id=s.github_app_id,
            app_private_key_b64=s.github_app_private_key_b64,
            app_installation_id=s.github_app_installation_id,
            on_call=router.hook("github"),
        )

    gemini: Optional[VertexGemini] = kwargs.get("gemini")
    if gemini is None and getattr(s, "vertex_configured", False):
        gemini = VertexGemini(
            s.gcp_project,
            s.gcp_location,
            s.gemini_model,
            on_call=router.hook("gemini"),
        )

    events: Optional[DynatraceEvents] = kwargs.get("events")
    if events is None and getattr(s, "dt_api_token", ""):
        events = DynatraceEvents(s.dt_classic_url, s.dt_api_token)

    pipeline = DarnPipeline(
        mcp=mcp,
        github=github,
        gemini=gemini,
        events=events,
        telemetry=telemetry,
        medic_router=router,
        diagnosis_runner=kwargs.get("diagnosis_runner"),
        settings_obj=s,
        http=kwargs.get("http"),
    )

    sabotage = GitHubSabotage(github) if github is not None else None

    health = DqlHealthSource(
        mcp,
        github,
        service_name=getattr(s, "demo_service_name", "loose-threads-shop"),
    )

    return {
        "sabotage": sabotage,
        "pipeline": pipeline,
        "health": health,
        "byo_validator": McpByoValidator(),
    }
