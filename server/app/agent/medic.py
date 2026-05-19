"""MedicRecorder — every MCP/GitHub/Gemini/verify call the agent makes is
recorded (name, kind, call count, wall seconds, tokens) and aggregated into the
MedicTrace shown in the heartbeat drawer. Numbers are measured, never invented;
cost is only computed when the pricing env vars are configured.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional

from ..integrations.vertex_gemini import compute_cost
from ..models import MedicRow, MedicTrace

Kind = str  # "mcp" | "gemini" | "github" | "verify" | "other"


class MedicRecorder:
    def __init__(self, *, telemetry: Any = None, root_span: Any = None):
        self._rows: dict[tuple[str, str], MedicRow] = {}
        self._telemetry = telemetry
        self._root_span = root_span
        self.trace_url: Optional[str] = None
        self.started_at = time.time()

    # ------------------------------------------------------------- recording

    def record(
        self,
        tool: str,
        kind: Kind,
        seconds: float,
        *,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        calls: int = 1,
    ) -> None:
        if self._telemetry is not None and self._root_span is not None:
            try:
                self._telemetry.record_call(
                    self._root_span,
                    tool,
                    seconds,
                    {
                        "darn.kind": kind,
                        "gen_ai.usage.input_tokens": tokens_in,
                        "gen_ai.usage.output_tokens": tokens_out,
                    },
                )
            except Exception:  # telemetry must never break the pipeline
                pass
        key = (tool, kind)
        row = self._rows.get(key)
        if row is None:
            self._rows[key] = MedicRow(
                tool=tool,
                kind=kind if kind in ("mcp", "gemini", "github", "verify") else "other",
                calls=calls,
                seconds=round(seconds, 3),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            return
        row.calls += calls
        row.seconds = round(row.seconds + seconds, 3)
        if tokens_in is not None:
            row.tokens_in = (row.tokens_in or 0) + tokens_in
        if tokens_out is not None:
            row.tokens_out = (row.tokens_out or 0) + tokens_out

    def hook(self, kind: Kind) -> Callable[..., None]:
        """Adapter matching the integrations' on_call signature:
        ``on_call(name, seconds, ok=True, tokens_in=None, tokens_out=None)``.
        Failed calls are recorded too — the medic reports what really happened."""

        def _on_call(
            name: str,
            seconds: float,
            *,
            ok: bool = True,
            tokens_in: Optional[int] = None,
            tokens_out: Optional[int] = None,
        ) -> None:
            self.record(name, kind, seconds, tokens_in=tokens_in, tokens_out=tokens_out)

        return _on_call

    @asynccontextmanager
    async def measure(self, tool: str, kind: Kind) -> AsyncIterator[None]:
        """Times a block and records it (record() also emits the OTel span
        from the same measured duration)."""
        started = time.monotonic()
        try:
            yield
        finally:
            self.record(tool, kind, time.monotonic() - started)

    def set_trace_url(self, url: Optional[str]) -> None:
        self.trace_url = url

    # --------------------------------------------------------------- summary

    def trace(self) -> MedicTrace:
        rows = list(self._rows.values())
        tokens_in = sum(r.tokens_in or 0 for r in rows)
        tokens_out = sum(r.tokens_out or 0 for r in rows)
        return MedicTrace(
            rows=[r.model_copy() for r in rows],
            tokens=tokens_in + tokens_out,
            cost_usd=compute_cost(tokens_in, tokens_out),
            wall_s=round(sum(r.seconds for r in rows), 3),
            trace_url=self.trace_url,
        )


class MedicRouter:
    """Routes the shared integration clients' ``on_call`` hooks to whichever
    incident's MedicRecorder is currently active (one live incident at a time
    by design — the demo lock). Calls made while no incident is active are
    dropped from the medic (health polling etc. is not incident work)."""

    def __init__(self) -> None:
        self.current: Optional[MedicRecorder] = None

    def hook(self, kind: Kind) -> Callable[..., None]:
        def _on_call(
            name: str,
            seconds: float,
            *,
            ok: bool = True,
            tokens_in: Optional[int] = None,
            tokens_out: Optional[int] = None,
        ) -> None:
            if self.current is not None:
                self.current.record(
                    name, kind, seconds, tokens_in=tokens_in, tokens_out=tokens_out
                )

        return _on_call
