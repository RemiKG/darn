"""Darn data model — the single shape shared by store, API, SSE, and the agent.

Every receipt the agent emits is one of the typed receipts below. Receipts are
append-only: once emitted they are never rewritten, because they are the product.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


def now_s() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- receipts

class ReceiptBase(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rcpt"))
    created_at: float = Field(default_factory=now_s)
    label: str = ""
    dynatrace_link: Optional[str] = None


class DavisProblemReceipt(ReceiptBase):
    type: Literal["davis_problem"] = "davis_problem"
    problem_id: str
    title: str
    severity: str = ""
    entity: str = ""
    started_at: Optional[str] = None
    evidence_chips: list[str] = []


class DqlReceipt(ReceiptBase):
    type: Literal["dql"] = "dql"
    query: str
    group: str = ""  # "numbers" | "exception" | "recovery" | ...


class DqlResultReceipt(ReceiptBase):
    type: Literal["dql_result"] = "dql_result"
    for_query_id: Optional[str] = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    truncated: bool = False


class TraceExcerptReceipt(ReceiptBase):
    type: Literal["trace_excerpt"] = "trace_excerpt"
    spans: list[dict[str, Any]] = []  # {name, depth, duration_ms, failed, status}
    trace_id: Optional[str] = None


class TimingRulerReceipt(ReceiptBase):
    type: Literal["timing_ruler"] = "timing_ruler"
    deploy_sha: str
    deploy_at: Optional[str] = None
    first_failure_at: Optional[str] = None
    gap_s: Optional[float] = None
    note: str = ""


class SuspectHunkReceipt(ReceiptBase):
    type: Literal["suspect_hunk"] = "suspect_hunk"
    path: str
    diff: str
    caption: str = ""


class ProposedDiffReceipt(ReceiptBase):
    type: Literal["proposed_diff"] = "proposed_diff"
    files: list[str] = []
    diff: str = ""


class RationaleReceipt(ReceiptBase):
    type: Literal["rationale"] = "rationale"
    text: str


class ModelMetaReceipt(ReceiptBase):
    type: Literal["model_meta"] = "model_meta"
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None


class PrReceipt(ReceiptBase):
    type: Literal["pr"] = "pr"
    repo: str
    branch: str
    number: Optional[int] = None
    title: str = ""
    url: Optional[str] = None
    toc: list[str] = []
    checks: list[dict[str, str]] = []  # {name, state}


class ApprovalReceipt(ReceiptBase):
    type: Literal["approval"] = "approval"
    by: str
    at: float = Field(default_factory=now_s)
    deploy_line: str = ""


class ReplayReceipt(ReceiptBase):
    type: Literal["replay"] = "replay"
    method: str = "POST"
    path: str = ""
    before_status: Optional[int] = None
    before_at: Optional[str] = None
    after_status: Optional[int] = None
    after_at: Optional[str] = None


class ClosureReceipt(ReceiptBase):
    type: Literal["closure"] = "closure"
    problem_id: str = ""
    closed_at: Optional[str] = None
    pr_comment_posted: bool = False
    annotation_sent: bool = False
    notebook_url: Optional[str] = None


class KnotReceipt(ReceiptBase):
    type: Literal["knot"] = "knot"
    reason: str
    evidence: str = ""


class NoteReceipt(ReceiptBase):
    type: Literal["note"] = "note"
    text: str


Receipt = Union[
    DavisProblemReceipt,
    DqlReceipt,
    DqlResultReceipt,
    TraceExcerptReceipt,
    TimingRulerReceipt,
    SuspectHunkReceipt,
    ProposedDiffReceipt,
    RationaleReceipt,
    ModelMetaReceipt,
    PrReceipt,
    ApprovalReceipt,
    ReplayReceipt,
    ClosureReceipt,
    KnotReceipt,
    NoteReceipt,
]


# ---------------------------------------------------------------- stages

STAGE_KEYS = ["detected", "diagnosed", "fix_written", "pr_open", "approved", "verified"]
STAGE_NAMES = {
    "detected": "Detected",
    "diagnosed": "Diagnosed",
    "fix_written": "Fix written",
    "pr_open": "PR open",
    "approved": "Approved",
    "verified": "Verified closed",
}

StageState = Literal["pending", "active", "done", "tied_off", "skipped"]


class Stage(BaseModel):
    key: str
    name: str
    state: StageState = "pending"
    started_at: Optional[float] = None
    done_at: Optional[float] = None
    receipts: list[Receipt] = []

    @property
    def elapsed_s(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.done_at if self.done_at is not None else now_s()
        return end - self.started_at


def fresh_stages() -> list[Stage]:
    return [Stage(key=k, name=STAGE_NAMES[k]) for k in STAGE_KEYS]


# ---------------------------------------------------------------- medic

class MedicRow(BaseModel):
    tool: str
    kind: Literal["mcp", "gemini", "github", "verify", "other"] = "other"
    calls: int = 1
    seconds: float = 0.0
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class MedicTrace(BaseModel):
    rows: list[MedicRow] = []
    tokens: int = 0
    cost_usd: Optional[float] = None
    wall_s: float = 0.0
    trace_url: Optional[str] = None


# ---------------------------------------------------------------- incident

IncidentStatus = Literal[
    "live", "verified_closed", "tied_off", "declined_reverted", "declined_timeout"
]


class Needle(BaseModel):
    holder_session: Optional[str] = None
    holder_label: str = "the needle-holder"
    last_seen: Optional[float] = None


class WallClockSummary(BaseModel):
    detected_to_pr_s: Optional[float] = None
    approved_to_verified_s: Optional[float] = None
    dql_receipts: int = 0
    token_cost_usd: Optional[float] = None


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inc"))
    kind: Literal["demo", "byo"] = "demo"
    defect_key: Optional[str] = None
    title: str = ""
    status: IncidentStatus = "live"
    problem_id: Optional[str] = None
    problem_url: Optional[str] = None
    service_name: str = ""
    repo: str = ""
    pr_number: Optional[int] = None
    sabotage_sha: Optional[str] = None
    started_at: float = Field(default_factory=now_s)
    ended_at: Optional[float] = None
    stage_index: int = 0
    stages: list[Stage] = Field(default_factory=fresh_stages)
    needle: Optional[Needle] = None
    watching: int = 0
    wall_clock_summary: Optional[WallClockSummary] = None
    medic: Optional[MedicTrace] = None

    def stage(self, key: str) -> Stage:
        for s in self.stages:
            if s.key == key:
                return s
        raise KeyError(key)


class IncidentSummary(BaseModel):
    id: str
    kind: str
    defect_key: Optional[str] = None
    title: str
    status: IncidentStatus
    started_at: float
    ended_at: Optional[float] = None
    detected_to_closed_s: Optional[float] = None
    pr_number: Optional[int] = None
    repo: str = ""


def summarize(inc: Incident) -> IncidentSummary:
    dtc = None
    if inc.ended_at is not None:
        dtc = inc.ended_at - inc.started_at
    return IncidentSummary(
        id=inc.id,
        kind=inc.kind,
        defect_key=inc.defect_key,
        title=inc.title,
        status=inc.status,
        started_at=inc.started_at,
        ended_at=inc.ended_at,
        detected_to_closed_s=dtc,
        pr_number=inc.pr_number,
        repo=inc.repo,
    )


# ---------------------------------------------------------------- health

class SparkPoint(BaseModel):
    t: float
    v: float
    anomalous: bool = False


class HealthCard(BaseModel):
    status: Literal["ok", "torn", "unavailable"] = "unavailable"
    error_rate: Optional[float] = None
    p95_ms: Optional[float] = None
    rpm: Optional[float] = None
    sparkline: list[SparkPoint] = []
    last_deploy_sha: Optional[str] = None
    last_deploy_ago_s: Optional[float] = None
    source: Literal["dql", "unavailable"] = "unavailable"
    reason: str = ""  # honest one-liner when unavailable


# ---------------------------------------------------------------- BYO

class ServiceMapping(BaseModel):
    service: str
    repo: str
    branch: str = "main"
    watch: bool = True
    paused: bool = False
    last_problem_at: Optional[float] = None
    prs_opened: int = 0


class ByoState(BaseModel):
    connected: bool = False
    tenant_host: str = ""
    services: list[dict[str, Any]] = []
    mappings: list[ServiceMapping] = []
    github_installed: bool = False
    github_repo: str = ""
