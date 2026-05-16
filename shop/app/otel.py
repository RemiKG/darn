"""OpenTelemetry, env-seamed.

When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the shop instruments FastAPI and
exports spans over OTLP/HTTP (e.g. to Dynatrace). Failed requests are marked as
error spans — that's the signal Davis reads. When the endpoint is unset this is
a total no-op: `get_tracer()` returns the API's built-in no-op tracer, so the
manual spans scattered through the app cost nothing and emit nothing.
"""

from __future__ import annotations

import os

from opentelemetry import trace

_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "loose-threads-shop").strip() or "loose-threads-shop"

# A module-level tracer. Until a provider is installed this is the no-op tracer,
# so spans opened against it do nothing and raise nothing.
tracer = trace.get_tracer("loose-threads-shop")


def get_tracer() -> trace.Tracer:
    return tracer


def init_otel(app) -> None:
    """Install a real exporter + FastAPI instrumentation if configured.

    No-op (and silent) when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
    # The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS
    # from the environment itself, so we don't have to thread them through.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    global tracer
    tracer = trace.get_tracer("loose-threads-shop")

    # Auto-instrument requests; FastAPIInstrumentor marks 5xx responses as error spans.
    FastAPIInstrumentor.instrument_app(app)
