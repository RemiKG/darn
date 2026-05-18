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
