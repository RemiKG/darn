"""Self-instrumentation seam (re-export).

The implementation lives in ``app.agent.otel`` (agent-pipeline lane); this
module is the contract-mandated import location ``app.otel``. No-op without
DT_API_TOKEN; see app/agent/otel.py for details.
"""

from .agent.otel import AgentTelemetry, build_telemetry

__all__ = ["AgentTelemetry", "build_telemetry", "get_telemetry"]

_singleton: AgentTelemetry | None = None


def get_telemetry() -> AgentTelemetry:
    """Lazy process-wide telemetry handle built from app.config.settings."""
    global _singleton
    if _singleton is None:
        _singleton = build_telemetry()
    return _singleton
