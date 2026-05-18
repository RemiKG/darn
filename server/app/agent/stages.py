"""The five pipeline stages, emitting receipts in display order.

Implements the AgentPipeline seam (duck-typed — seams.py is owned by the core
server and is never imported at module load):

    async run_detect(incident, emitter)
    async run_diagnose_fix_pr(incident, emitter)
    async run_verify(incident, emitter)

The StageEmitter the core provides has: emit_receipt(stage_key, receipt),
stage_started(key), stage_done(key), set_medic(trace), fail(reason). Every
emitter call here tolerates both sync and async implementations.

Honesty law: receipts only record REAL executed calls; a stage
completes only on real evidence (the detect stage finishes when Davis raises a
real problem — never on a timer); missing dependencies become plain-language
note receipts, never invented data.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..integrations.dynatrace_events import DynatraceEvents, problem_link, trace_link
from ..integrations.dynatrace_mcp import (
    DynatraceMcpClient,
    DynatraceMcpError,
    DynatraceScopeError,
)
from ..integrations.github_client import GitHubClient, GitHubError
from ..integrations.vertex_gemini import FixResult, VertexGemini
from ..models import (
    ClosureReceipt,
    DavisProblemReceipt,
    DqlReceipt,
    DqlResultReceipt,
    Incident,
    KnotReceipt,
    ModelMetaReceipt,
    NoteReceipt,
    PrReceipt,
    ProposedDiffReceipt,
    RationaleReceipt,
    ReplayReceipt,
    SuspectHunkReceipt,
    TimingRulerReceipt,
    TraceExcerptReceipt,
    WallClockSummary,
    now_s,
)
from .medic import MedicRecorder, MedicRouter
from .runner import AdkDiagnosisRunner, CapturedCall, DiagnosisResult, ForensicsToolkit

log = logging.getLogger("darn.agent.stages")

SCOPE_REASON = "Dynatrace token lacks Grail read scopes on this deployment"

# Replay shapes per defect: the SAME endpoint the defect breaks.
DEFECT_REPLAYS: dict[str, tuple[str, str, Optional[dict]]] = {
    "checkout-null": ("POST", "/api/checkout", {"cart_id": "darn-replay-empty"}),
    "catalog-stampede": ("GET", "/api/catalog", None),
    "penny-shaver": ("POST", "/api/pay", {"order_id": "darn-replay", "amount_cents": 999}),
    "inventory-grenade": ("POST", "/api/inventory/restock", {"sock_id": "monday-heel", "qty": 7}),
}


# ----------------------------------------------------------------- utilities

async def _emit(emitter: Any, method: str, *args: Any) -> None:
    fn = getattr(emitter, method, None)
    if fn is None:
        return
    result = fn(*args)
    if inspect.isawaitable(result):
        await result


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _to_epoch(value: Any) -> Optional[float]:
    """ISO string, epoch seconds, or epoch milliseconds -> epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _extract_problems(payload: Any) -> list[dict]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if isinstance(payload, dict):
        for key in ("problems", "result", "items", "records"):
            if isinstance(payload.get(key), list):
                return [p for p in payload[key] if isinstance(p, dict)]
        if "problemId" in payload or "displayId" in payload:
            return [payload]
        return []
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return []


def _problem_id(p: dict) -> str:
    return str(p.get("displayId") or p.get("problemId") or p.get("id") or "")


def _problem_title(p: dict) -> str:
    return str(p.get("title") or p.get("displayName") or p.get("problemTitle") or "Davis problem")


def _problem_start(p: dict) -> Optional[float]:
    for key in ("startTime", "start_time", "startTimestamp", "firstSeenTms"):
        epoch = _to_epoch(p.get(key))
        if epoch is not None:
            return epoch
    return None


def _problem_entities(p: dict) -> list[str]:
    names: list[str] = []
    for key in ("affectedEntities", "impactedEntities", "rootCauseEntity", "affected_entities"):
        value = p.get(key)
        items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
            elif isinstance(item, str):
                names.append(item)
    return names


def _evidence_chips(p: dict) -> list[str]:
    chips: list[str] = []
    if p.get("severityLevel"):
        chips.append(str(p["severityLevel"]).replace("_", " ").lower())
    if p.get("impactLevel"):
        chips.append(f"impact: {str(p['impactLevel']).replace('_', ' ').lower()}")
    entities = _problem_entities(p)
    if entities:
        chips.append(entities[0])
    evidence = p.get("evidenceDetails") or p.get("evidence")
    if isinstance(evidence, dict) and evidence.get("totalCount"):
        chips.append(f"{evidence['totalCount']} evidence items")
    elif isinstance(evidence, list) and evidence:
        chips.append(f"{len(evidence)} evidence items")
    return chips[:5]


def _tabulate(data: Any, max_rows: int = 12) -> tuple[list[str], list[list[Any]], bool]:
    """DQL result payload -> (columns, rows, truncated). Verbatim values."""
    records: Optional[list] = None
    if isinstance(data, dict):
        for key in ("records", "results", "rows", "data"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
    elif isinstance(data, list):
        records = data
    if records is not None and records and all(isinstance(r, dict) for r in records):
        columns: list[str] = []
        for record in records:
            for key in record.keys():
                if key not in columns:
                    columns.append(key)
        rows = [[record.get(c) for c in columns] for record in records[:max_rows]]
        return columns, rows, len(records) > max_rows
    if records is not None:
        rows = [[r] for r in records[:max_rows]]
        return ["value"], rows, len(records) > max_rows
    if data is None:
        return [], [], False
    blob = data if isinstance(data, str) else json.dumps(data)
    return ["result"], [[blob[:800]]], len(blob) > 800


def _classify_dql(query: str) -> tuple[str, str]:
    q = query.lower()
    if "fetch logs" in q:
        return "exception", "The exception"
    if "min(" in q or "onset" in q or "earliest" in q:
        return "timing", "The timing"
    return "numbers", "The numbers"


def _span_shaped(columns: list[str], rows: list[list[Any]]) -> bool:
    cols = {c.lower() for c in columns}
    has_name = bool(cols & {"span.name", "span_name", "endpoint.name", "endpoint", "url.path"})
    has_duration = any("duration" in c for c in cols)
    return bool(rows) and has_name and has_duration


def _build_spans(columns: list[str], rows: list[list[Any]], limit: int = 5) -> list[dict[str, Any]]:
    def col(record: dict, *names: str) -> Any:
        for n in names:
            for key, value in record.items():
                if key.lower() == n:
                    return value
        return None

    spans = []
    for row in rows[:limit]:
        record = dict(zip(columns, row))
        duration = col(record, "duration", "span.duration", "duration_ms")
        duration_ms: Optional[float] = None
        epoch = _to_epoch(duration) if not isinstance(duration, (int, float)) else None
        if isinstance(duration, (int, float)):
            duration_ms = float(duration) / 1_000_000 if float(duration) > 100_000 else float(duration)
        elif epoch is not None:
            duration_ms = epoch * 1000
        failed = col(record, "request.is_failed", "failed", "is_failed")
        status = col(record, "http.response.status_code", "status", "span.status_code")
        spans.append(
            {
                "name": str(
                    col(record, "span.name", "span_name", "endpoint.name", "endpoint", "url.path")
                    or "span"
                ),
                "depth": 0,  # honest: no parent info -> no invented hierarchy
                "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
                "failed": bool(failed) or (str(status).startswith("5") if status else False),
                "status": str(status) if status is not None else "",
            }
        )
    return spans


def _extract_trace_id(columns: list[str], rows: list[list[Any]]) -> Optional[str]:
    for i, c in enumerate(columns):
        if c.lower() in ("trace.id", "trace_id", "traceid"):
            for row in rows:
                if row[i]:
                    return str(row[i])
    return None


def _hunks(patch: str) -> list[tuple[int, int, str]]:
    """Split a unified-diff patch into (new_start, new_len, hunk_text)."""
    out: list[tuple[int, int, str]] = []
    current: list[str] = []
    start = length = 0
    for line in (patch or "").splitlines():
        if line.startswith("@@"):
            if current:
                out.append((start, length, "\n".join(current)))
            current = [line]
            try:
                new_part = line.split("+")[1].split("@@")[0].strip()
                bits = new_part.split(",")
                start = int(bits[0])
                length = int(bits[1]) if len(bits) > 1 else 1
            except (IndexError, ValueError):
                start, length = 0, 0
        elif current:
            current.append(line)
    if current:
        out.append((start, length, "\n".join(current)))
    return out


def _match_suspect(
    frames: list[Any], files: list[dict]
) -> Optional[tuple[str, str, Any]]:
    """Intersect stack frames with deploy diff -> (path, hunk_text, frame)."""
    for frame in frames:
        fpath = (getattr(frame, "path", "") or "").replace("\\", "/").lstrip("/")
        if not fpath:
            continue
        base = fpath.split("/")[-1]
        for f in files:
            filename = f.get("filename", "")
            if not (filename.endswith(fpath) or fpath.endswith(filename) or filename.split("/")[-1] == base):
                continue
            patch = f.get("patch", "")
            if not patch:
                continue
            line_no = int(getattr(frame, "line", 0) or 0)
            hunks = _hunks(patch)
            for start, length, text in hunks:
                if start <= line_no <= start + max(length, 1):
                    return filename, _cap_lines(text, 14), frame
            if hunks:
                return filename, _cap_lines(hunks[0][2], 14), frame
    return None


def _cap_lines(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n])


def _markdown_table(columns: list[str], rows: list[list[Any]], limit: int = 6) -> str:
    if not columns:
        return "_(no rows)_"
    head = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "|" + "---|" * len(columns)
    body = [
        "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
        for row in rows[:limit]
    ]
    return "\n".join([head, sep, *body])


# ------------------------------------------------------------------ context

@dataclass
class _IncidentCtx:
    medic: MedicRecorder
    root_span: Any = None
    problem: dict = field(default_factory=dict)
    diagnosis: Optional[DiagnosisResult] = None
    fix: Optional[FixResult] = None
    dql_count: int = 0
    trace_emitted: bool = False
    scope_noted: bool = False
    deploy: Optional[dict] = None
    suspect: Optional[dict] = None
    replay: Optional[dict] = None
    branch: str = ""
    fix_commit_sha: str = ""
    dql_pairs: list[tuple[DqlReceipt, DqlResultReceipt]] = field(default_factory=list)
    file_cache: dict[str, str] = field(default_factory=dict)


class DarnPipeline:
    """AgentPipeline implementation (demo and BYO incidents alike)."""

    def __init__(
        self,
        *,
        mcp: Optional[DynatraceMcpClient] = None,
        github: Optional[GitHubClient] = None,
        gemini: Optional[VertexGemini] = None,
        events: Optional[DynatraceEvents] = None,
        telemetry: Any = None,
        medic_router: Optional[MedicRouter] = None,
        diagnosis_runner: Any = None,
        settings_obj: Any = None,
        http: Optional[httpx.AsyncClient] = None,
        settle_seconds: float = 20.0,
        check_poll_seconds: float = 15.0,
        checks_timeout_s: float = 900.0,
        closure_timeout_s: float = 1800.0,
    ):
        if settings_obj is None:
            from ..config import settings as settings_obj  # type: ignore[no-redef]
        self.settings = settings_obj
        self.mcp = mcp
        self.github = github
        self.gemini = gemini
        self.events = events
        self.telemetry = telemetry
        self.router = medic_router or MedicRouter()
        self.diagnosis_runner = diagnosis_runner
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self.settle_seconds = settle_seconds
        self.check_poll_seconds = check_poll_seconds
        self.checks_timeout_s = checks_timeout_s
        self.closure_timeout_s = closure_timeout_s
        self._ctx: dict[str, _IncidentCtx] = {}

    # ------------------------------------------------------------- plumbing

    def ctx_for(self, incident: Incident) -> _IncidentCtx:
        ctx = self._ctx.get(incident.id)
        if ctx is None:
            root = None
            if self.telemetry is not None:
                root = self.telemetry.start_root(
                    f"darn incident {incident.id}",
                    {"incident.id": incident.id, "incident.kind": incident.kind,
                     "defect.key": incident.defect_key},
                )
            medic = MedicRecorder(telemetry=self.telemetry, root_span=root)
            if self.telemetry is not None:
                medic.set_trace_url(self.telemetry.trace_url(root))
            ctx = _IncidentCtx(medic=medic, root_span=root)
            self._ctx[incident.id] = ctx
        self.router.current = ctx.medic
        return ctx

    def medic_trace(self, incident_id: str) -> Any:
        ctx = self._ctx.get(incident_id)
        return ctx.medic.trace() if ctx else None

    async def _push_medic(self, incident: Incident, emitter: Any) -> None:
        ctx = self.ctx_for(incident)
        trace = ctx.medic.trace()
        incident.medic = trace
        await _emit(emitter, "set_medic", trace)

    async def _tie_off(self, incident: Incident, emitter: Any, stage_key: str) -> None:
        fn = getattr(emitter, "stage_tied_off", None)
        if fn is not None:
            result = fn(stage_key)
            if inspect.isawaitable(result):
                await result
        else:
            stage = incident.stage(stage_key)
            stage.state = "tied_off"
            stage.done_at = now_s()
        incident.status = "tied_off"
        incident.ended_at = now_s()
        if self.telemetry is not None:
            self.telemetry.end_root(self.ctx_for(incident).root_span)

    # ------------------------------------------------------------ stage 1

    async def run_detect(self, incident: Incident, emitter: Any) -> None:
        """Poll query-problems until Davis raises the REAL problem. Never
        completes on a timer; logs and retries through scope errors."""
        ctx = self.ctx_for(incident)
        try:
            await _emit(emitter, "stage_started", "detected")
            if self.mcp is None:
                await _emit(emitter, "fail", "Dynatrace is not configured on this deployment")
                return
            poll = float(getattr(self.settings, "poll_seconds", 30) or 30)
            service = incident.service_name or getattr(self.settings, "demo_service_name", "")
            not_before = incident.started_at - 120
            while True:
                problem = None
                try:
                    result = await self.mcp.call_tool(
                        "query-problems", {"status": "ACTIVE", "history": "30m"}
                    )
                    problem = self._match_problem(result.data or result.text, service, not_before)
                except DynatraceScopeError as e:
                    if not ctx.scope_noted:
                        ctx.scope_noted = True
                        await _emit(
                            emitter,
                            "emit_receipt",
                            "detected",
                            NoteReceipt(
                                label="Waiting on Dynatrace",
                                text=(
                                    f"{SCOPE_REASON} — the gateway answered: "
                                    f"“{e}”. Darn keeps polling; detection "
                                    "completes the moment a properly-scoped token lands."
                                ),
                            ),
                        )
                    log.warning("detect: scope error from gateway: %s", e)
                except DynatraceMcpError as e:
                    log.warning("detect: gateway error: %s", e)
                if problem is not None:
                    ctx.problem = problem
                    pid = _problem_id(problem)
                    incident.problem_id = pid
                    env = getattr(self.settings, "dt_environment", "")
                    # the new Davis problems app wants the LONG internal id
                    link_id = str(problem.get("problemId") or pid)
                    incident.problem_url = problem_link(env, link_id) if env else None
                    receipt = DavisProblemReceipt(
                        label="Raised by Davis before Darn moved a muscle.",
                        problem_id=pid,
                        title=_problem_title(problem),
                        severity=str(problem.get("severityLevel", "")),
                        entity=(_problem_entities(problem) or [service])[0],
                        started_at=_iso(_problem_start(problem)),
                        evidence_chips=_evidence_chips(problem),
                        dynatrace_link=incident.problem_url,
                    )
                    await _emit(emitter, "emit_receipt", "detected", receipt)
                    await _emit(emitter, "stage_done", "detected")
                    await self._push_medic(incident, emitter)
                    return
                await asyncio.sleep(poll)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — honest failure beats a silent hang
            log.exception("detect stage failed")
            await _emit(emitter, "fail", f"detect: {e}")

    def _match_problem(self, payload: Any, service: str, not_before: float) -> Optional[dict]:
        for problem in _extract_problems(payload):
            status = str(problem.get("status", "ACTIVE")).upper()
            if status not in ("ACTIVE", "OPEN", ""):
                continue
            names = _problem_entities(problem)
            blob = json.dumps(problem)
            if service and service not in blob and not any(service in n for n in names):
                continue
            start = _problem_start(problem)
            if start is not None and start < not_before:
                continue
            return problem
        return None

    # --------------------------------------------------------- stages 2-4

    async def run_diagnose_fix_pr(self, incident: Incident, emitter: Any) -> None:
        ctx = self.ctx_for(incident)
        try:
            ok = await self._diagnose(incident, emitter, ctx)
            if not ok:
                return  # tied off (already emitted) — pipeline stops here
            await self._fix(incident, emitter, ctx)
            await self._open_pr(incident, emitter, ctx)
            await self._push_medic(incident, emitter)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("diagnose/fix/pr failed")
            await _emit(emitter, "fail", f"{e}")

    async def _diagnose(self, incident: Incident, emitter: Any, ctx: _IncidentCtx) -> bool:
        await _emit(emitter, "stage_started", "diagnosed")
        service = incident.service_name or getattr(self.settings, "demo_service_name", "")
        env = getattr(self.settings, "dt_environment", "")

        async def on_capture(call: CapturedCall) -> None:
            if call.tool != "execute-dql":
                return
            if not call.ok:
                if call.scope_error and not ctx.scope_noted:
                    ctx.scope_noted = True
                    await _emit(
                        emitter, "emit_receipt", "diagnosed",
                        NoteReceipt(label="Scope limit", text=f"{SCOPE_REASON} — “{call.error}”"),
                    )
                return
            ctx.dql_count += 1
            query = str(call.arguments.get("dqlQueryString", ""))
            group, label = _classify_dql(query)
            dql = DqlReceipt(query=query, group=group, label=label)
            await _emit(emitter, "emit_receipt", "diagnosed", dql)
            columns, rows, truncated = _tabulate(call.data)
            result = DqlResultReceipt(
                for_query_id=dql.id,
                columns=columns,
                rows=rows,
                truncated=truncated,
                label=f"{label} — result",
            )
            await _emit(emitter, "emit_receipt", "diagnosed", result)
            ctx.dql_pairs.append((dql, result))
            if not ctx.trace_emitted and _span_shaped(columns, rows):
                ctx.trace_emitted = True
                trace_id = _extract_trace_id(columns, rows)
                link = trace_link(env, trace_id) if (trace_id and env) else None
                await _emit(
                    emitter, "emit_receipt", "diagnosed",
                    TraceExcerptReceipt(
                        label="The exception — trace excerpt",
                        spans=_build_spans(columns, rows),
                        trace_id=trace_id,
                        dynatrace_link=link,
                    ),
                )

        if self.mcp is None:
            await _emit(emitter, "fail", "Dynatrace is not configured on this deployment")
            return False
        toolkit = ForensicsToolkit(
            self.mcp,
            dql_budget=int(getattr(self.settings, "dql_budget_per_incident", 12)),
            on_capture=on_capture,
        )
        runner = self.diagnosis_runner or AdkDiagnosisRunner(
            project=getattr(self.settings, "gcp_project", ""),
            location=getattr(self.settings, "gcp_location", "global"),
            model_name=getattr(self.settings, "gemini_model", "gemini-3-flash-preview"),
        )
        context_note = ""
        if incident.defect_key:
            context_note = "The service deployed a code change shortly before the problem."
        diagnosis, stats = await runner.diagnose(
            toolkit=toolkit,
            problem_id=incident.problem_id or "",
            service_name=service,
            context_note=context_note,
        )
        ctx.diagnosis = diagnosis
        ctx.medic.record(
            "darn_diagnostician (ADK)",
            "gemini",
            stats.seconds,
            tokens_in=stats.tokens_in,
            tokens_out=stats.tokens_out,
            calls=max(1, stats.llm_calls),
        )

        # --- The timing: deploy ∩ onset -------------------------------------
        deploy = await self._find_deploy(incident, diagnosis)
        onset_epoch = _to_epoch(diagnosis.onset) or _problem_start(ctx.problem)
        if deploy is None or (not diagnosis.code_shaped and not incident.defect_key):
            evidence_bits = [diagnosis.narrative or "No code-shaped signal in the forensics."]
            if onset_epoch:
                evidence_bits.append(f"first failure {_iso(onset_epoch)}")
            evidence_bits.append("Darn stops here. No PR. No guessing.")
            await _emit(
                emitter, "emit_receipt", "diagnosed",
                KnotReceipt(
                    label="Tied off",
                    reason="This hole isn't in the code.",
                    evidence=" ".join(evidence_bits),
                ),
            )
            await self._tie_off(incident, emitter, "diagnosed")
            await self._push_medic(incident, emitter)
            return False
        ctx.deploy = deploy
        gap_s = None
        if onset_epoch is not None and deploy.get("epoch") is not None:
            gap_s = round(onset_epoch - deploy["epoch"], 1)
        sha7 = deploy["sha"][:7]
        if deploy.get("solo", True):
            note = f"First failure {int(gap_s)} seconds after deploy `{sha7}`. No other deploys in the window." if gap_s is not None else f"Deploy `{sha7}` is the only deploy in the window."
        else:
            note = f"First failure {int(gap_s)} seconds after deploy `{sha7}` — the nearest of {deploy.get('count', 2)} deploys in the window." if gap_s is not None else f"Deploy `{sha7}` is the nearest deploy in the window."
        await _emit(
            emitter, "emit_receipt", "diagnosed",
            TimingRulerReceipt(
                label="The timing",
                deploy_sha=deploy["sha"],
                deploy_at=deploy.get("date"),
                first_failure_at=_iso(onset_epoch),
                gap_s=gap_s,
                note=note,
            ),
        )

        # --- The suspect: stack frame ∩ deploy diff --------------------------
        files = deploy.get("files", [])
        suspect = _match_suspect(diagnosis.stack_frames, files)
        if suspect is not None:
            path, hunk, frame = suspect
            caption = (
                f"Stack frame `{frame.function or path.split('/')[-1]} "
                f"({frame.path}:{frame.line})` matches this hunk of `{sha7}`."
            )
        elif files and any(f.get("patch") for f in files):
            f0 = next(f for f in files if f.get("patch"))
            path = f0["filename"]
            hunk = _cap_lines(_hunks(f0["patch"])[0][2] if _hunks(f0["patch"]) else f0["patch"], 14)
            gap_text = f" First failure follows it by {int(gap_s)} s." if gap_s is not None else ""
            caption = f"The deploy in the window touches `{path}`.{gap_text}"
        else:
            await _emit(
                emitter, "emit_receipt", "diagnosed",
                KnotReceipt(
                    label="Tied off",
                    reason="This hole isn't in the code.",
                    evidence=(
                        f"Deploy `{sha7}` contains no inspectable code change that matches "
                        "the failure. Darn stops here. No PR. No guessing."
                    ),
                ),
            )
            await self._tie_off(incident, emitter, "diagnosed")
            await self._push_medic(incident, emitter)
            return False
        ctx.suspect = {"path": path, "hunk": hunk}
        await _emit(
            emitter, "emit_receipt", "diagnosed",
            SuspectHunkReceipt(label="The suspect", path=path, diff=hunk, caption=caption),
        )

        # Record the failing request NOW (real measured 'before' for stage 6).
        await self._record_before_replay(incident, ctx)

        await _emit(
            emitter, "emit_receipt", "diagnosed",
            NoteReceipt(
                label="Stage footer",
                text=(
                    "Every block above is copy-pasteable into your tenant. Same query, "
                    f"same numbers. DQL queries this diagnosis: {ctx.dql_count}"
                ),
            ),
        )
        await _emit(emitter, "stage_done", "diagnosed")
        await self._push_medic(incident, emitter)
        return True

    async def _find_deploy(
        self, incident: Incident, diagnosis: DiagnosisResult
    ) -> Optional[dict]:
        if self.github is None:
            return None
        try:
            if incident.sabotage_sha:
                commit = await self.github.get_commit(incident.sabotage_sha)
                parent = commit["parents"][0] if commit["parents"] else None
                files: list[dict] = []
                if parent:
                    cmp = await self.github.compare(parent, incident.sabotage_sha)
                    files = cmp["files"]
                else:
                    files = commit.get("files", [])
                epoch = _to_epoch(commit.get("date"))
                # honesty check for the 'no other deploys' claim
                solo, count = True, 1
                onset = _to_epoch(diagnosis.onset) or now_s()
                since = _iso(min(onset, epoch or onset) - 1800)
                try:
                    branch = await self.github.get_repo_default_branch()
                    recent = await self.github.list_commits(branch, since=since)
                    count = max(1, len(recent))
                    solo = count <= 1 or all(
                        c["sha"] == incident.sabotage_sha for c in recent
                    )
                except GitHubError:
                    pass
                return {
                    "sha": incident.sabotage_sha,
                    "date": commit.get("date"),
                    "epoch": epoch,
                    "files": files,
                    "solo": solo,
                    "count": count,
                }
            # BYO: nearest commit on the default branch with commit_ts <= onset
            onset = _to_epoch(diagnosis.onset)
            branch = await self.github.get_repo_default_branch()
            since = _iso((onset or now_s()) - 1800)
            commits = await self.github.list_commits(branch, since=since)
            candidates = [
                c for c in commits
                if onset is None or (_to_epoch(c["date"]) or 0) <= onset
            ]
            if not candidates:
                return None
            best = max(candidates, key=lambda c: _to_epoch(c["date"]) or 0)
            detail = await self.github.get_commit(best["sha"])
            parent = detail["parents"][0] if detail["parents"] else None
            files = (await self.github.compare(parent, best["sha"]))["files"] if parent else detail.get("files", [])
            return {
                "sha": best["sha"],
                "date": best["date"],
                "epoch": _to_epoch(best["date"]),
                "files": files,
                "solo": len(candidates) <= 1,
                "count": len(candidates),
            }
        except GitHubError as e:
            log.warning("deploy lookup failed: %s", e)
            return None

    async def _record_before_replay(self, incident: Incident, ctx: _IncidentCtx) -> None:
        shape = DEFECT_REPLAYS.get(incident.defect_key or "")
        shop_url = getattr(self.settings, "shop_url", "")
        if shape is None or not shop_url:
            return
        method, path, payload = shape
        async with ctx.medic.measure("replay probe (before)", "verify"):
            status, ms = await self._probe(method, f"{shop_url}{path}", payload)
        ctx.replay = {
            "method": method,
            "path": path,
            "payload": payload,
            "before_status": status,
            "before_at": _iso(now_s()),
            "before_ms": ms,
        }

    async def _probe(self, method: str, url: str, payload: Optional[dict]) -> tuple[Optional[int], float]:
        started = time.monotonic()
        try:
            resp = await self._http.request(method, url, json=payload)
            return resp.status_code, round((time.monotonic() - started) * 1000, 1)
        except httpx.HTTPError:
            return None, round((time.monotonic() - started) * 1000, 1)

    # ------------------------------------------------------------- stage 3

    async def _fix(self, incident: Incident, emitter: Any, ctx: _IncidentCtx) -> None:
        await _emit(emitter, "stage_started", "fix_written")
        if self.gemini is None:
            await _emit(emitter, "fail", "Gemini on Vertex AI is not configured")
            raise RuntimeError("Gemini on Vertex AI is not configured")
        briefing = await self._build_briefing(incident, ctx)
        fix = await self.gemini.generate_fix(briefing)
        ctx.fix = fix
        diff = await self._proposal_diff(incident, ctx, fix)
        await _emit(
            emitter, "emit_receipt", "fix_written",
            ProposedDiffReceipt(
                label="Written by Gemini on Vertex AI, briefed with the receipts above.",
                files=[f.path for f in fix.proposal.files],
                diff=diff,
            ),
        )
        await _emit(
            emitter, "emit_receipt", "fix_written",
            RationaleReceipt(label="Rationale", text=fix.proposal.rationale),
        )
        await _emit(
            emitter, "emit_receipt", "fix_written",
            ModelMetaReceipt(
                label="Measured during this incident",
                model=fix.model,
                tokens_in=fix.tokens_in,
                tokens_out=fix.tokens_out,
                cost_usd=fix.cost_usd,
            ),
        )
        await _emit(emitter, "stage_done", "fix_written")
        await self._push_medic(incident, emitter)

    async def _get_file_cached(self, ctx: _IncidentCtx, path: str, ref: str) -> str:
        if path not in ctx.file_cache:
            try:
                ctx.file_cache[path] = (await self.github.get_file(path, ref=ref))["content"]
            except GitHubError:
                ctx.file_cache[path] = ""
        return ctx.file_cache[path]

    async def _build_briefing(self, incident: Incident, ctx: _IncidentCtx) -> str:
        receipts = [
            r.model_dump(mode="json")
            for stage in incident.stages
            for r in stage.receipts
        ]
        current_files: dict[str, str] = {}
        if self.github is not None:
            branch = await self.github.get_repo_default_branch()
            paths: list[str] = []
            if ctx.suspect:
                paths.append(ctx.suspect["path"])
            for f in (ctx.deploy or {}).get("files", []):
                if f.get("filename") and f["filename"] not in paths:
                    paths.append(f["filename"])
            for path in paths[:3]:
                content = await self._get_file_cached(ctx, path, branch)
                if content:
                    current_files[path] = content[:12000]
        payload = {
            "incident": {
                "title": incident.title,
                "defect_key": incident.defect_key,
                "service": incident.service_name,
                "problem_id": incident.problem_id,
            },
            "diagnosis": ctx.diagnosis.model_dump(mode="json") if ctx.diagnosis else {},
            "receipts": receipts,
            "current_files": current_files,
        }
        briefing = json.dumps(payload, indent=1, default=str)
        if len(briefing) > 90000:
            payload["receipts"] = receipts[:20]
            briefing = json.dumps(payload, indent=1, default=str)[:90000]
        return (
            "Evidence dossier for the incident below. Write the smallest correct fix.\n\n"
            + briefing
        )

    async def _proposal_diff(self, incident: Incident, ctx: _IncidentCtx, fix: FixResult) -> str:
        chunks: list[str] = []
        branch = await self.github.get_repo_default_branch() if self.github else "main"
        for f in fix.proposal.files:
            current = await self._get_file_cached(ctx, f.path, branch) if self.github else ""
            diff = difflib.unified_diff(
                current.splitlines(),
                f.new_content.splitlines(),
                fromfile=f"a/{f.path}",
                tofile=f"b/{f.path}",
                lineterm="",
            )
            chunks.append("\n".join(diff))
        return "\n\n".join(chunks)

    # ------------------------------------------------------------- stage 4

    async def _open_pr(self, incident: Incident, emitter: Any, ctx: _IncidentCtx) -> None:
        await _emit(emitter, "stage_started", "pr_open")
        if self.github is None:
            await _emit(emitter, "fail", "GitHub is not configured")
            raise RuntimeError("GitHub is not configured")
        fix = ctx.fix
        assert fix is not None
        base = await self.github.get_repo_default_branch()
        base_sha = await self.github.get_branch_sha(base)
        branch = f"darn/fix-{incident.defect_key or incident.id}"
        await self.github.create_branch(base_sha, branch)
        title = fix.proposal.pr_title or f"Mend: {incident.title or incident.defect_key}"
        ctx.branch = branch
        ctx.fix_commit_sha = await self.github.commit_files(
            {f.path: f.new_content for f in fix.proposal.files}, title, branch
        )
        body, toc = self._build_dossier(incident, ctx)
        pr = await self.github.create_pr(title, body, head=branch, base=base)
        incident.pr_number = pr["number"]
        try:
            checks = await self.github.get_checks_for_ref(ctx.fix_commit_sha)
        except GitHubError:
            checks = []
        await _emit(
            emitter, "emit_receipt", "pr_open",
            PrReceipt(
                label="The PR body is the dossier. The receipts travel with the fix.",
                repo=self.github.repo,
                branch=branch,
                number=pr["number"],
                title=title,
                url=pr["url"],
                toc=toc,
                checks=[
                    {"name": c["name"], "state": c["conclusion"] or c["status"]}
                    for c in checks
                ],
            ),
        )
        await _emit(emitter, "stage_done", "pr_open")
        await self._push_medic(incident, emitter)

    def _build_dossier(self, incident: Incident, ctx: _IncidentCtx) -> tuple[str, list[str]]:
        toc: list[str] = []
        parts: list[str] = []
        problem_url = incident.problem_url or ""
        # Problem
        toc.append("Problem")
        parts.append("## Problem\n")
        title = _problem_title(ctx.problem) if ctx.problem else incident.title
        parts.append(
            f"**{title}** — Davis problem `{incident.problem_id}`"
            + (f" ([open in Dynatrace]({problem_url}))" if problem_url else "")
        )
        if ctx.problem:
            start = _iso(_problem_start(ctx.problem))
            if start:
                parts.append(f"\nStarted `{start}` · service `{incident.service_name}`")
        # Receipts
        n = len(ctx.dql_pairs)
        toc.append(f"Receipts (DQL ×{n})")
        parts.append(f"\n## Receipts (DQL ×{n})\n")
        parts.append("_Every block below is copy-pasteable into Dynatrace. Same query, same numbers._\n")
        for dql, result in ctx.dql_pairs:
            parts.append(f"**{dql.label}**\n\n```\n{dql.query}\n```\n")
            parts.append(_markdown_table(result.columns, result.rows) + "\n")
        # Trace
        trace_receipts = [
            r for s in incident.stages for r in s.receipts if r.type == "trace_excerpt"
        ]
        if trace_receipts:
            toc.append("Trace")
            parts.append("\n## Trace\n")
            t = trace_receipts[0]
            for span in t.spans:
                status = f" `{span.get('status')}`" if span.get("status") else ""
                dur = f" — {span.get('duration_ms')} ms" if span.get("duration_ms") is not None else ""
                flag = " ✕" if span.get("failed") else ""
                parts.append(f"- `{span.get('name')}`{dur}{status}{flag}")
            if t.dynatrace_link:
                parts.append(f"\n[Open trace in Dynatrace]({t.dynatrace_link})")
        # Suspect hunk
        if ctx.suspect:
            toc.append("Suspect hunk")
            parts.append("\n## Suspect hunk\n")
            if ctx.deploy:
                parts.append(
                    f"Deploy `{ctx.deploy['sha'][:7]}` at `{ctx.deploy.get('date', '')}`:"
                )
            parts.append(f"\n```diff\n{ctx.suspect['hunk']}\n```\n")
        # Fix
        toc.append("Fix")
        parts.append("\n## Fix\n")
        if ctx.fix:
            parts.append(ctx.fix.proposal.rationale + "\n")
            for section in ctx.fix.proposal.pr_body_sections:
                parts.append(f"\n### {section.heading}\n\n{section.body_markdown}\n")
        # How to verify
        toc.append("How to verify")
        parts.append("\n## How to verify\n")
        if ctx.replay:
            shop_url = getattr(self.settings, "shop_url", "")
            parts.append(
                f"1. Replay the failing request: `{ctx.replay['method']} "
                f"{shop_url}{ctx.replay['path']}` — it returned "
                f"`{ctx.replay.get('before_status')}` during the incident."
            )
        if ctx.dql_pairs:
            parts.append("2. Re-run the recovery query in your tenant:\n")
            parts.append(f"```\n{ctx.dql_pairs[0][0].query}\n```")
        if problem_url:
            parts.append(f"3. Watch the Davis problem close: [{incident.problem_id}]({problem_url})")
        parts.append("\n---\n_Fixes with receipts. — Darn_")
        return "\n".join(parts), toc

    # ------------------------------------------------------------- stage 6

    async def run_verify(self, incident: Incident, emitter: Any) -> None:
        """After merge + deploy: replay, recovery DQL, Davis closure — the
        problem card closing is the ONLY thing that completes this stage."""
        ctx = self.ctx_for(incident)
        try:
            await _emit(emitter, "stage_started", "verified")
            if self.github is None or self.mcp is None:
                await _emit(emitter, "fail", "verify requires GitHub and Dynatrace")
                return
            # 1. wait for the merge commit's checks (the deploy)
            merge_sha = ""
            if incident.pr_number:
                try:
                    merge_sha = (await self.github.get_pr(incident.pr_number)).get(
                        "merge_commit_sha", ""
                    )
                except GitHubError as e:
                    log.warning("verify: get_pr failed: %s", e)
            if merge_sha:
                outcome = await self._wait_checks(merge_sha)
                if outcome == "failure":
                    await _emit(
                        emitter, "fail",
                        "CI on the merge commit concluded failure — the fix did not deploy",
                    )
                    return
                if outcome == "none":
                    await _emit(
                        emitter, "emit_receipt", "verified",
                        NoteReceipt(
                            label="CI",
                            text="No CI checks reported on the merge commit; proceeded after the settle delay.",
                        ),
                    )
            await asyncio.sleep(self.settle_seconds)
            # 2. replay the previously-failing request
            await self._verify_replay(incident, emitter, ctx)
            # 3. recovery DQL
            await self._verify_recovery_dql(incident, emitter, ctx)
            # 4. Davis closure — the referee
            closed_at = await self._wait_problem_closed(incident, ctx)
            if closed_at is None:
                await _emit(
                    emitter, "fail",
                    f"Davis problem {incident.problem_id} did not close within "
                    f"{int(self.closure_timeout_s // 60)} minutes",
                )
                return
            comment_posted = await self._post_closure_comment(incident, ctx, closed_at)
            annotation_sent = await self._send_annotation(incident, emitter)
            await _emit(
                emitter, "emit_receipt", "verified",
                ClosureReceipt(
                    label="The referee says it's mended.",
                    problem_id=incident.problem_id or "",
                    closed_at=closed_at,
                    pr_comment_posted=comment_posted,
                    annotation_sent=annotation_sent,
                    dynatrace_link=incident.problem_url,
                ),
            )
            # 5. wall-clock summary — measured from real stage timestamps
            incident.wall_clock_summary = self._wall_clock(incident, ctx)
            incident.status = "verified_closed"
            incident.ended_at = now_s()
            if self.telemetry is not None:
                self.telemetry.end_root(ctx.root_span)
            await self._push_medic(incident, emitter)
            await _emit(emitter, "stage_done", "verified")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("verify stage failed")
            await _emit(emitter, "fail", f"verify: {e}")

    async def _wait_checks(self, sha: str) -> str:
        """'success' | 'failure' | 'none' — polls real CI checks."""
        deadline = time.monotonic() + self.checks_timeout_s
        empty_polls = 0
        while time.monotonic() < deadline:
            try:
                checks = await self.github.get_checks_for_ref(sha)
            except GitHubError:
                checks = []
            if not checks:
                empty_polls += 1
                if empty_polls >= 3:
                    return "none"
            else:
                if any(c["conclusion"] in ("failure", "timed_out", "cancelled") for c in checks):
                    return "failure"
                if all(c["status"] == "completed" for c in checks):
                    return "success"
            await asyncio.sleep(self.check_poll_seconds)
        return "failure"

    async def _verify_replay(self, incident: Incident, emitter: Any, ctx: _IncidentCtx) -> None:
        shape = ctx.replay or (
            dict(
                zip(
                    ("method", "path", "payload"),
                    DEFECT_REPLAYS.get(incident.defect_key or "", (None, None, None)),
                )
            )
            if incident.defect_key in DEFECT_REPLAYS
            else None
        )
        shop_url = getattr(self.settings, "shop_url", "")
        if not shape or not shape.get("method") or not shop_url:
            await _emit(
                emitter, "emit_receipt", "verified",
                NoteReceipt(
                    label="Replay",
                    text="No replayable request shape was recorded for this incident — replay skipped.",
                ),
            )
            return
        async with ctx.medic.measure("replay (after)", "verify"):
            after_status, after_ms = await self._probe(
                shape["method"], f"{shop_url}{shape['path']}", shape.get("payload")
            )
        await _emit(
            emitter, "emit_receipt", "verified",
            ReplayReceipt(
                label=f"{shape['method']} {shape['path']} — re-sent ({after_ms} ms)",
                method=shape["method"],
                path=shape["path"],
                before_status=shape.get("before_status"),
                before_at=shape.get("before_at"),
                after_status=after_status,
                after_at=_iso(now_s()),
            ),
        )

    async def _verify_recovery_dql(self, incident: Incident, emitter: Any, ctx: _IncidentCtx) -> None:
        service = incident.service_name or getattr(self.settings, "demo_service_name", "")
        query = (
            "fetch spans, from: now() - 15m\n"
            f'| filter service.name == "{service}" and request.is_failed == true\n'
            "| summarize failures = count(), by: { endpoint.name }\n"
            "| sort failures desc"
        )
        try:
            result = await self.mcp.call_tool("execute-dql", {"dqlQueryString": query})
        except (DynatraceScopeError, DynatraceMcpError) as e:
            await _emit(
                emitter, "emit_receipt", "verified",
                NoteReceipt(label="Recovery query", text=f"Recovery DQL could not run: {e}"),
            )
            return
        dql = DqlReceipt(query=query, group="recovery", label="Recovery")
        await _emit(emitter, "emit_receipt", "verified", dql)
        columns, rows, truncated = _tabulate(result.data)
        recovery_result = DqlResultReceipt(
            for_query_id=dql.id, columns=columns, rows=rows, truncated=truncated,
            label="Recovery — result",
        )
        await _emit(emitter, "emit_receipt", "verified", recovery_result)
        ctx.dql_pairs.append((dql, recovery_result))

    async def _wait_problem_closed(self, incident: Incident, ctx: _IncidentCtx) -> Optional[str]:
        poll = max(10, int(getattr(self.settings, "poll_seconds", 30)))
        deadline = time.monotonic() + self.closure_timeout_s
        while time.monotonic() < deadline:
            try:
                result = await self.mcp.call_tool(
                    "get-problem-by-id", {"problemId": incident.problem_id}
                )
                problems = _extract_problems(result.data or result.text)
                problem = problems[0] if problems else None
                if problem is not None:
                    status = str(problem.get("status", "")).upper()
                    if status in ("CLOSED", "RESOLVED"):
                        end = (
                            _to_epoch(problem.get("endTime"))
                            or _to_epoch(problem.get("end_time"))
                            or now_s()
                        )
                        return _iso(end)
            except (DynatraceScopeError, DynatraceMcpError) as e:
                log.warning("closure poll error: %s", e)
            await asyncio.sleep(poll)
        return None

    async def _post_closure_comment(
        self, incident: Incident, ctx: _IncidentCtx, closed_at: str
    ) -> bool:
        if not incident.pr_number:
            return False
        lines = [
            "## Verified closed",
            "",
            f"Davis problem `{incident.problem_id}` closed at `{closed_at}`"
            + (f" — [problem card]({incident.problem_url})" if incident.problem_url else "")
            + ".",
        ]
        replay = next(
            (r for s in incident.stages for r in s.receipts if r.type == "replay"), None
        )
        if replay is not None:
            lines.append(
                f"Replay: `{replay.method} {replay.path}` — "
                f"`{replay.before_status}` during the incident, `{replay.after_status}` now."
            )
        recovery = next(
            (
                r
                for s in incident.stages
                for r in s.receipts
                if r.type == "dql" and r.group == "recovery"
            ),
            None,
        )
        if recovery is not None:
            lines.append("\nRecovery query (re-run it yourself):\n")
            lines.append(f"```\n{recovery.query}\n```")
        lines.append("\n_'Fixed' is not the agent's opinion. — Darn_")
        try:
            await self.github.comment_pr(incident.pr_number, "\n".join(lines))
            return True
        except GitHubError as e:
            log.warning("closure comment failed: %s", e)
            return False

    async def _send_annotation(self, incident: Incident, emitter: Any) -> bool:
        if self.events is None or not self.events.enabled:
            await _emit(
                emitter, "emit_receipt", "verified",
                NoteReceipt(
                    label="Deployment annotation",
                    text="Deployment annotation skipped — DT_API_TOKEN is not configured on this deployment.",
                ),
            )
            return False
        try:
            await self.events.send_deployment(
                f"Darn mend deployed — PR #{incident.pr_number}",
                service_name=incident.service_name
                or getattr(self.settings, "demo_service_name", ""),
                properties={
                    "incident": incident.id,
                    "pr": str(incident.pr_number or ""),
                    "problem": incident.problem_id or "",
                },
            )
            return True
        except Exception as e:  # noqa: BLE001
            await _emit(
                emitter, "emit_receipt", "verified",
                NoteReceipt(label="Deployment annotation", text=f"Annotation send failed: {e}"),
            )
            return False

    def _wall_clock(self, incident: Incident, ctx: _IncidentCtx) -> WallClockSummary:
        def _span(a_key: str, a_attr: str, b_key: str, b_attr: str) -> Optional[float]:
            a = getattr(incident.stage(a_key), a_attr, None)
            b = getattr(incident.stage(b_key), b_attr, None)
            if b is None and b_key == "verified":
                b = now_s()  # this summary is computed just before stage_done stamps it
            if a is None or b is None:
                return None
            return round(b - a, 1)

        dql_receipts = sum(
            1 for s in incident.stages for r in s.receipts if r.type == "dql"
        )
        medic = ctx.medic.trace()
        return WallClockSummary(
            detected_to_pr_s=_span("detected", "done_at", "pr_open", "done_at"),
            approved_to_verified_s=_span("approved", "done_at", "verified", "done_at")
            or _span("approved", "started_at", "verified", "done_at"),
            dql_receipts=dql_receipts,
            token_cost_usd=medic.cost_usd,
        )
