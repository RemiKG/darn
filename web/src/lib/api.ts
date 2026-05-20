/**
 * Typed fetch wrappers for every REST endpoint.
 *
 * The TS interfaces mirror server/app/models.py —
 * all timestamps are epoch SECONDS as floats, exactly as pydantic emits them.
 * All URLs are relative ("/api/...") — dev mode proxies them to :4601,
 * production serves the SPA from the same origin. Session is an httponly
 * cookie, hence `credentials: "include"` on every call.
 */

// ------------------------------------------------------------------ receipts

export interface ReceiptBase {
  id: string;
  created_at: number;
  label: string;
  dynatrace_link?: string | null;
}

export interface DavisProblemReceipt extends ReceiptBase {
  type: "davis_problem";
  problem_id: string;
  title: string;
  severity: string;
  entity: string;
  started_at: string | null;
  evidence_chips: string[];
}

export interface DqlReceipt extends ReceiptBase {
  type: "dql";
  query: string;
  /** "numbers" | "exception" | "recovery" | ... */
  group: string;
}

export interface DqlResultReceipt extends ReceiptBase {
  type: "dql_result";
  for_query_id: string | null;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  truncated: boolean;
}

export interface TraceSpan {
  name?: string;
  depth?: number;
  duration_ms?: number | null;
  failed?: boolean;
  status?: string | number;
  [key: string]: unknown;
}

export interface TraceExcerptReceipt extends ReceiptBase {
  type: "trace_excerpt";
  spans: TraceSpan[];
  trace_id: string | null;
}

export interface TimingRulerReceipt extends ReceiptBase {
  type: "timing_ruler";
  deploy_sha: string;
  deploy_at: string | null;
  first_failure_at: string | null;
  gap_s: number | null;
  note: string;
}

export interface SuspectHunkReceipt extends ReceiptBase {
  type: "suspect_hunk";
  path: string;
  diff: string;
  caption: string;
}

export interface ProposedDiffReceipt extends ReceiptBase {
  type: "proposed_diff";
  files: string[];
  diff: string;
}

export interface RationaleReceipt extends ReceiptBase {
  type: "rationale";
  text: string;
}

export interface ModelMetaReceipt extends ReceiptBase {
  type: "model_meta";
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number | null;
}

export interface PrCheck {
  name: string;
  state: string;
}

export interface PrReceipt extends ReceiptBase {
  type: "pr";
  repo: string;
  branch: string;
  number: number | null;
  title: string;
  url: string | null;
  toc: string[];
  checks: PrCheck[];
}

export interface ApprovalReceipt extends ReceiptBase {
  type: "approval";
  by: string;
  at: number;
  deploy_line: string;
}

export interface ReplayReceipt extends ReceiptBase {
  type: "replay";
  method: string;
  path: string;
  before_status: number | null;
  before_at: string | null;
  after_status: number | null;
  after_at: string | null;
}

export interface ClosureReceipt extends ReceiptBase {
  type: "closure";
  problem_id: string;
  closed_at: string | null;
  pr_comment_posted: boolean;
  annotation_sent: boolean;
  notebook_url: string | null;
}

export interface KnotReceipt extends ReceiptBase {
  type: "knot";
  reason: string;
  evidence: string;
}

export interface NoteReceipt extends ReceiptBase {
  type: "note";
  text: string;
}

export type Receipt =
  | DavisProblemReceipt
  | DqlReceipt
  | DqlResultReceipt
  | TraceExcerptReceipt
  | TimingRulerReceipt
  | SuspectHunkReceipt
  | ProposedDiffReceipt
  | RationaleReceipt
  | ModelMetaReceipt
  | PrReceipt
  | ApprovalReceipt
  | ReplayReceipt
  | ClosureReceipt
  | KnotReceipt
  | NoteReceipt;

export type ReceiptType = Receipt["type"];

// ------------------------------------------------------------------ stages

export type StageKey =
  | "detected"
  | "diagnosed"
  | "fix_written"
  | "pr_open"
  | "approved"
  | "verified";

export type StageState = "pending" | "active" | "done" | "tied_off" | "skipped";

export interface Stage {
  key: StageKey;
  name: string;
  state: StageState;
  started_at: number | null;
  done_at: number | null;
  /** computed server-side; may be absent on the wire */
  elapsed_s?: number | null;
  receipts: Receipt[];
}

// ------------------------------------------------------------------ medic

export type MedicRowKind = "mcp" | "gemini" | "github" | "verify" | "other";

export interface MedicRow {
  tool: string;
  kind: MedicRowKind;
  calls: number;
  seconds: number;
  tokens_in?: number | null;
  tokens_out?: number | null;
}

export interface MedicTrace {
  rows: MedicRow[];
  tokens: number;
  cost_usd: number | null;
  wall_s: number;
  trace_url: string | null;
}

// ------------------------------------------------------------------ incident

export type IncidentStatus =
  | "live"
  | "verified_closed"
  | "tied_off"
  | "declined_reverted"
  | "declined_timeout";

export type IncidentKind = "demo" | "byo";

export interface Needle {
  holder_session: string | null;
  holder_label: string;
  last_seen: number | null;
}

export interface WallClockSummary {
  detected_to_pr_s: number | null;
  approved_to_verified_s: number | null;
  dql_receipts: number;
  token_cost_usd: number | null;
}

export interface Incident {
  id: string;
  kind: IncidentKind;
  defect_key: string | null;
  title: string;
  status: IncidentStatus;
  problem_id: string | null;
  problem_url: string | null;
  service_name: string;
  repo: string;
  pr_number: number | null;
  sabotage_sha: string | null;
  started_at: number;
  ended_at: number | null;
  stage_index: number;
  stages: Stage[];
  needle: Needle | null;
  watching: number;
  wall_clock_summary: WallClockSummary | null;
  medic: MedicTrace | null;
}

export interface IncidentSummary {
  id: string;
  kind: string;
  defect_key: string | null;
  title: string;
  status: IncidentStatus;
  started_at: number;
  ended_at: number | null;
  detected_to_closed_s: number | null;
  pr_number: number | null;
  repo: string;
}

// ------------------------------------------------------------------ health

export interface SparkPoint {
  t: number;
  v: number;
  anomalous: boolean;
}

export interface HealthCard {
  status: "ok" | "torn" | "unavailable";
  error_rate: number | null;
  p95_ms: number | null;
  rpm: number | null;
  sparkline: SparkPoint[];
  last_deploy_sha: string | null;
  last_deploy_ago_s: number | null;
  source: "dql" | "unavailable";
  /** honest one-liner when unavailable */
  reason: string;
}

// ------------------------------------------------------------------ state snapshot

export interface AppStateSnapshot {
  health: HealthCard;
  live_incident_id: string | null;
  cooldown_until: number | null;
  mended: IncidentSummary[];
  last_mend: IncidentSummary | null;
  byo_configured: boolean;
  dynatrace: { configured: boolean; mcp_ok: boolean };
  github: { configured: boolean; mode: "app" | "pat" | "none" };
  repo_url: string;
  tenant_url: string;
}

// ------------------------------------------------------------------ demo / presence

export type DefectKey =
  | "checkout-null"
  | "catalog-stampede"
  | "penny-shaver"
  | "inventory-grenade";

export interface TearResponse {
  incident_id: string;
}

export interface PresenceInfo {
  watching: number;
  holder: boolean;
  holder_label: string;
  can_pickup: boolean;
}

/** SSE "presence" event payload (global bus carries incident_id; per-incident may not) */
export interface PresenceEvent {
  incident_id?: string;
  watching: number;
  holder?: boolean;
  holder_label?: string;
  can_pickup?: boolean;
}

/** SSE "cooldown" event payload */
export interface CooldownEvent {
  until: number | null;
}

// ------------------------------------------------------------------ BYO

export interface ByoService {
  name: string;
  health?: string;
  [key: string]: unknown;
}

export interface ServiceMapping {
  service: string;
  repo: string;
  branch: string;
  watch: boolean;
  paused: boolean;
  last_problem_at: number | null;
  prs_opened: number;
}

export interface YoursConnectResponse {
  ok: boolean;
  services: ByoService[];
}

export interface YoursState {
  connected: boolean;
  tenant_host: string;
  services: ByoService[];
  mappings: ServiceMapping[];
  github: { installed: boolean; repo: string };
  mends: IncidentSummary[];
}

export interface GithubInstallUrl {
  url: string | null;
  configured: boolean;
}

// ------------------------------------------------------------------ settings
// The server (settings_api.py) is the source of truth;
// locked toggles are server-enforced constants either way.

export interface DarnSettings {
  detection: {
    poll_seconds: number;
    problem_scope: "deploy_linked" | "any_code_smell";
    quiet_hours: { enabled: boolean; start: string; end: string; timezone: string };
  };
  diagnosis: {
    dql_budget_per_incident: number;
    lookback_minutes: number;
    /** locked on — "Not a setting. Darn never guesses." */
    stop_when_not_code: true;
  };
  fix_policy: {
    branch_prefix: string;
    pr_labels: string[];
    draft_prs: boolean;
    max_changed_files: number;
    max_diff_lines: number;
    path_denylist: string[];
    /** locked on — "No PR storms. Ever." */
    one_open_pr_per_service: true;
  };
  oversight: {
    /** locked off — "This switch exists to show you it's off." */
    darn_can_merge: false;
    decline_tidy: boolean;
    webhook_url: string;
  };
  budgets: {
    token_budget_per_fix: number;
    monthly_spend_cap_usd: number;
    dql_budget_per_day: number;
  };
  data: {
    retention: "forever" | "30d" | "90d" | "365d";
  };
  medic: {
    /** locked on — "The medic doesn't get to take off the monitor." */
    self_traces: true;
    share_timings_with_demo: boolean;
  };
}

// ------------------------------------------------------------------ fetch plumbing

/** Thrown for non-2xx responses; `body` is the parsed JSON error when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** The server's `{error: "..."}` code when present (e.g. "locked", "cooldown"). */
  get code(): string | null {
    if (this.body && typeof this.body === "object" && "error" in this.body) {
      const v = (this.body as Record<string, unknown>).error;
      return typeof v === "string" ? v : null;
    }
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body as T;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

function post<T>(path: string, payload?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
}

function put<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: JSON.stringify(payload) });
}

// ------------------------------------------------------------------ endpoints

export const api = {
  // state & health
  getState: () => get<AppStateSnapshot>("/api/state"),
  getHealthCard: () => get<HealthCard>("/api/health-card"),

  // demo
  /** 201 {incident_id} | throws ApiError 409 locked / 425 cooldown / 503 not_configured */
  tear: (defect: DefectKey) => post<TearResponse>("/api/demo/tear", { defect }),

  // incidents
  listIncidents: () => get<{ incidents: IncidentSummary[] }>("/api/incidents"),
  getIncident: (id: string) => get<Incident>(`/api/incidents/${id}`),
  postPresence: (id: string) => post<PresenceInfo>(`/api/incidents/${id}/presence`),
  pickup: (id: string) => post<{ holder: boolean }>(`/api/incidents/${id}/pickup`),
  approve: (id: string) => post<unknown>(`/api/incidents/${id}/approve`),
  decline: (id: string) => post<unknown>(`/api/incidents/${id}/decline`),
  getMedic: (id: string) => get<MedicTrace>(`/api/incidents/${id}/medic`),

  // bring your own
  yoursConnect: (tenant_url: string, platform_token: string) =>
    post<YoursConnectResponse>("/api/yours/connect", { tenant_url, platform_token }),
  getYours: () => get<YoursState>("/api/yours"),
  yoursMapping: (mapping: { service: string; repo: string; branch: string; watch: boolean }) =>
    post<unknown>("/api/yours/mappings", mapping),
  yoursPause: (service: string) => post<unknown>("/api/yours/pause", { service }),
  yoursDisconnect: (confirm_host: string) =>
    post<unknown>("/api/yours/disconnect", { confirm_host }),
  yoursGithubInstallUrl: () => get<GithubInstallUrl>("/api/yours/github/install-url"),

  // settings
  getSettings: () => get<DarnSettings>("/api/settings"),
  putSettings: (settings: DarnSettings) => put<DarnSettings>("/api/settings", settings),
};

export type Api = typeof api;
