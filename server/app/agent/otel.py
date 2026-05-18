"""Self-instrumentation — the medic wears a heart monitor.

When enabled (OTEL_ENABLED + DT env + DT_API_TOKEN with ingest scope), the
agent ships its own spans to the SAME Dynatrace tenant that watches the shop:
OTLP/HTTP to ``{DT_CLASSIC_URL}/api/v2/otlp/v1/traces`` with an ``Api-Token``
header. One span per pipeline stage, one child span per tool call, with token
and cost attributes.

Without the token this is a complete no-op: no provider is created, no export
is attempted, no warnings are spammed. The code is complete behind the seam —
flipping the env vars turns it on with zero code changes.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from ..integrations.dynatrace_events import trace_link


class AgentTelemetry:
    def __init__(
        self,
        *,
        enabled: bool = False,
        classic_url: str = "",
        api_token: str = "",
        dt_environment: str = "",
        service_name: str = "darn-agent",
    ):
        self.enabled = bool(enabled and classic_url and api_token)
        self._classic_url = classic_url.rstrip("/")
        self._api_token = api_token
        self._dt_environment = dt_environment.rstrip("/")
        self._service_name = service_name
        self._tracer: Any = None
        self._provider: Any = None

    # ----------------------------------------------------------------- setup

    def _ensure(self) -> Any:
        if not self.enabled:
            return None
        if self._tracer is None:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(
                endpoint=f"{self._classic_url}/api/v2/otlp/v1/traces",
                headers={"Authorization": f"Api-Token {self._api_token}"},
            )
            self._provider = TracerProvider(
                resource=Resource.create({"service.name": self._service_name})
            )
            self._provider.add_span_processor(BatchSpanProcessor(exporter))
            self._tracer = self._provider.get_tracer("darn.agent")
        return self._tracer

    # ----------------------------------------------------------------- spans

    def start_root(self, name: str, attributes: Optional[dict[str, Any]] = None) -> Any:
        """Start a long-lived root span (one per incident). Returns a handle
        (or None when disabled) — pass it to child()/end_root()."""
        tracer = self._ensure()
        if tracer is None:
            return None
        span = tracer.start_span(name, attributes=_clean(attributes))
        return span

    @contextmanager
    def child(
        self, root: Any, name: str, attributes: Optional[dict[str, Any]] = None
    ) -> Iterator[Any]:
        tracer = self._ensure()
        if tracer is None or root is None:
            yield None
            return
        from opentelemetry import trace

        ctx = trace.set_span_in_context(root)
        with tracer.start_as_current_span(name, context=ctx, attributes=_clean(attributes)) as span:
            yield span

    def record_call(
        self, root: Any, name: str, seconds: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        """Retroactive span for an already-measured call (start/end computed
        from the REAL measured wall time — same numbers as the medic row)."""
        tracer = self._ensure()
        if tracer is None or root is None:
            return
        from opentelemetry import trace

        end_ns = time.time_ns()
        start_ns = end_ns - int(max(0.0, seconds) * 1e9)
        ctx = trace.set_span_in_context(root)
        span = tracer.start_span(
            name, context=ctx, start_time=start_ns, attributes=_clean(attributes)
        )
        span.end(end_time=end_ns)

    def end_root(self, root: Any) -> None:
        if root is not None:
            root.end()

    def trace_id_of(self, span: Any) -> Optional[str]:
        if span is None:
            return None
        ctx = span.get_span_context()
        if not ctx.trace_id:
            return None
        return format(ctx.trace_id, "032x")

    def trace_url(self, span: Any) -> Optional[str]:
        """Deep link to this trace in the tenant (medic drawer link)."""
        trace_id = self.trace_id_of(span)
        if not trace_id or not self._dt_environment:
            return None
        return trace_link(self._dt_environment, trace_id)

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()
            self._provider = None
            self._tracer = None


def _clean(attributes: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not attributes:
        return {}
    return {k: v for k, v in attributes.items() if v is not None}


def build_telemetry(settings_obj: Any = None) -> AgentTelemetry:
    if settings_obj is None:
        from ..config import settings as settings_obj  # type: ignore[no-redef]
    return AgentTelemetry(
        enabled=getattr(settings_obj, "otel_enabled", False),
        classic_url=getattr(settings_obj, "dt_classic_url", ""),
        api_token=getattr(settings_obj, "dt_api_token", ""),
        dt_environment=getattr(settings_obj, "dt_environment", ""),
        service_name=getattr(settings_obj, "otel_service_name", "darn-agent"),
    )
