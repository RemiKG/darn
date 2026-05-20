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
