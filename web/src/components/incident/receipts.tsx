/**
 * Receipt renderers for the incident view — one faithful block per receipt
 * type in the tagged union (models.py / api.ts):
 *   davis_problem, dql (+ paired dql_result), trace_excerpt, timing_ruler,
 *   suspect_hunk, proposed_diff, rationale, model_meta, pr, approval,
 *   replay, closure, knot, note.
 * Every numeral is mono.
 */

import { Fragment, type ReactNode } from "react";
import {
  type ClosureReceipt,
  type DavisProblemReceipt,
  type DqlReceipt,
  type DqlResultReceipt,
  type Incident,
  type ModelMetaReceipt,
  type NoteReceipt,
  type PrReceipt,
  type ProposedDiffReceipt,
  type RationaleReceipt,
  type Receipt,
  type ReplayReceipt,
  type Stage,
  type SuspectHunkReceipt,
  type TimingRulerReceipt,
  type TraceExcerptReceipt,
  type ApprovalReceipt,
  type KnotReceipt,
  type SparkPoint,
} from "../../lib/api";
import { groupedInt, money, shortSha, utcClock } from "../../lib/format";
import { cx } from "../../lib/cx";
import CopyButton from "../CopyButton";
import DiffBlock from "../DiffBlock";
import DqlBlock from "../DqlBlock";
import Spark from "../Spark";
import { PillOk } from "../Pills";

// ------------------------------------------------------------------ helpers

export function findReceipt<T extends Receipt["type"]>(
  receipts: Receipt[],
  type: T
): Extract<Receipt, { type: T }> | undefined {
  return receipts.find((r) => r.type === type) as Extract<Receipt, { type: T }> | undefined;
}

export function findIncidentReceipt<T extends Receipt["type"]>(
  incident: Incident,
  type: T
): Extract<Receipt, { type: T }> | undefined {
  for (const stage of incident.stages) {
    const hit = findReceipt(stage.receipts, type);
    if (hit) {
      return hit;
    }
  }
  return undefined;
}

/**
 * Wrap numeral/code-ish tokens (clock times, counts, short shas, stack-frame
 * refs, dotted identifiers, call refs) of a plain-text data string in mono
 * `.num` spans — receipts arrive as text, these render mono.
 */
const NUMISH_RE =
  /([\w.]+\s?\([\w./]+:\d+\)|\b\w+(?:\.\w+)+(?:\(\))?|\b\w+\(\)|\d{1,2}:\d{2}(?::\d{2})?|\$\d[\d.,]*|[+\-]?\d[\d.,]*(?:\s?%)?|\b[0-9a-f]{7,12}\b)/g;

export function wrapNums(text: string, bold = false): ReactNode {
  const parts = text.split(NUMISH_RE);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className="num" style={bold ? { fontWeight: 600 } : undefined}>
        {part}
      </span>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    )
  );
}

/** "+38 s" — trims float noise (38 → "38", 38.5 → "38.5"). */
function trimNum(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
}

/** Unified-diff bookkeeping: added new-side line numbers + add/rem counts. */
export function diffStats(diff: string): { addLines: number[]; adds: number; rems: number } {
  const addLines: number[] = [];
  let adds = 0;
  let rems = 0;
  let newNo = 0;
  for (const raw of diff.replace(/\r\n/g, "\n").split("\n")) {
    const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      newNo = parseInt(hunk[1], 10);
      continue;
    }
    if (raw.startsWith("+++") || raw.startsWith("---")) {
      continue;
    }
    if (raw.startsWith("+")) {
      addLines.push(newNo);
      newNo++;
      adds++;
    } else if (raw.startsWith("-")) {
      rems++;
    } else if (raw.length > 0) {
      newNo++;
    }
  }
  return { addLines, adds, rems };
}

/** Line numbers referenced as ":118" inside a caption (stack-frame refs). */
function captionLineRefs(caption: string): number[] {
  const out: number[] = [];
  for (const m of caption.matchAll(/:(\d+)/g)) {
    out.push(parseInt(m[1], 10));
  }
  return out;
}

/** "02:57" / "02:57:14" → seconds-of-day (spark x-axis), else null. */
function parseClock(v: unknown): number | null {
  if (typeof v !== "string") {
    return null;
  }
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(v.trim());
  if (!m) {
    return null;
  }
  return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60 + (m[3] ? parseInt(m[3], 10) : 0);
}

// ------------------------------------------------------------------ glyphs

/** Amber tear severity glyph (Davis problem card). */
function SevTear() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M2 10 H7.5" stroke="#1B2A44" strokeWidth="2" strokeLinecap="round" />
      <path d="M12.5 10 H18" stroke="#1B2A44" strokeWidth="2" strokeLinecap="round" />
      <path d="M8 9.2 L9.6 7.4" stroke="#A9690F" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M8.2 11 L9.8 12.6" stroke="#A9690F" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 9 L10.6 7.6" stroke="#A9690F" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M11.9 11.2 L10.4 12.4" stroke="#A9690F" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

/** Stitched-closed glyph (Davis closure card). */
function SevClosed() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M2 10 H18" stroke="#1B2A44" strokeWidth="2" strokeLinecap="round" />
      <path
        d="M7 10 l2.4 2.4 L14 7.2"
        stroke="#1B2A44"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="translate(0,-0.4)"
      />
    </svg>
  );
}

// ------------------------------------------------------------------ davis problem

export function DavisProblemCard({ receipt }: { receipt: DavisProblemReceipt }) {
  return (
    <div className="well davis" style={{ marginTop: 16 }}>
      <div className="top">
        <span className="sev">
          <SevTear />
        </span>
        <div>
          <div className="ttl">{receipt.title}</div>
          <div className="sub">raised by Davis</div>
        </div>
      </div>
      <div className="grid">
        <div className="kv">
          <div className="k">problem ID</div>
          <div className="v">
            <span className="num">{receipt.problem_id}</span>
            <CopyButton
              text={receipt.problem_id}
              label=""
              className="minicopy"
              aria-label="Copy problem ID"
            />
          </div>
        </div>
        <div className="kv">
          <div className="k">affected entity</div>
          <div className="v">
            <span className="num">{receipt.entity}</span>
          </div>
        </div>
        <div className="kv">
          <div className="k">started</div>
          <div className="v">
            <span className="num">{receipt.started_at ?? "—"}</span>
          </div>
        </div>
      </div>
      {receipt.evidence_chips.length > 0 && (
        <div className="chips">
          {receipt.evidence_chips.map((chip, i) => (
            <span key={i} className="chip">
              <span className="num">{chip}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ dql + result

function hasStackColumn(result: DqlResultReceipt): boolean {
  return result.columns.some((c) => /stack/i.test(c));
}

/** The exception result, rendered as a message + stack well. */
function ExceptionWell({ result }: { result: DqlResultReceipt }) {
  const stackCol = result.columns.findIndex((c) => /stack/i.test(c));
  const hitsCol = result.columns.findIndex((c) => /hits|count|failures/i.test(c));
  const msgCol = result.columns.findIndex((_c, i) => i !== stackCol && i !== hitsCol);
  const row = result.rows[0] ?? [];
  const message = msgCol >= 0 ? String(row[msgCol] ?? "") : "";
  const hits = hitsCol >= 0 ? row[hitsCol] : null;
  const stack = stackCol >= 0 ? String(row[stackCol] ?? "") : "";
  const stackLines = stack
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return (
    <div className="well excwell">
      {message}
      {hits !== null && hits !== undefined && (
        <span className="soft">
          {" "}
          — <span className="num">{String(hits)}</span> hits
        </span>
      )}
      {stackLines.length > 0 && (
        <span className="soft">
          {stackLines.map((l, i) => (
            <Fragment key={i}>
              {"\n  "}
              {l}
            </Fragment>
          ))}
        </span>
      )}
    </div>
  );
}

export function DqlGroup({
  receipt,
  result,
}: {
  receipt: DqlReceipt;
  result: DqlResultReceipt | null;
}) {
  const compact = receipt.group !== "numbers";
  if (result && hasStackColumn(result)) {
    return (
      <>
        <DqlBlock query={receipt.query} compact={compact} />
        <ExceptionWell result={result} />
      </>
    );
  }
  return (
    <DqlBlock
      query={receipt.query}
      compact={compact}
      result={result ? { columns: result.columns, rows: result.rows } : null}
      hotRow={receipt.group === "numbers" && result && result.rows.length > 0 ? 0 : undefined}
    />
  );
}

// ------------------------------------------------------------------ recovery (dql + spark)

function sparkFromResult(result: DqlResultReceipt | null): {
  points: SparkPoint[];
  axis: string[];
} {
  if (!result || result.rows.length < 2 || result.columns.length < 2) {
    return { points: [], axis: [] };
  }
  const raw = result.rows.map((row, i) => ({
    t: parseClock(row[0]) ?? i,
    v: typeof row[1] === "number" ? row[1] : Number(row[1]) || 0,
    label: String(row[0] ?? ""),
  }));
  let vMin = Infinity;
  let vMax = -Infinity;
  for (const p of raw) {
    vMin = Math.min(vMin, p.v);
    vMax = Math.max(vMax, p.v);
  }
  const threshold = vMax > vMin ? vMin + 0.25 * (vMax - vMin) : Infinity;
  const points = raw.map((p) => ({ t: p.t, v: p.v, anomalous: p.v > threshold }));
  const n = raw.length;
  const picks = [0, Math.floor((n - 1) / 3), Math.floor((2 * (n - 1)) / 3), n - 1];
  const axis = [...new Set(picks)].map((i) => raw[i].label);
  return { points, axis };
}

export function RecoveryBlock({
  receipt,
  result,
}: {
  receipt: DqlReceipt;
  result: DqlResultReceipt | null;
}) {
  const { points, axis } = sparkFromResult(result);
  return (
    <div className="recov">
      <DqlBlock query={receipt.query} compact className="rcv" />
      <div className="sparkcard">
        <div className="sl">error rate · stitched closed</div>
        {points.length >= 2 ? (
          <Spark points={points} width={312} height={78} axisLabels={axis} />
        ) : (
          <p className="cap">recovery numbers land here once measured</p>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ trace excerpt

export function TraceExcerpt({ receipt }: { receipt: TraceExcerptReceipt }) {
  const spans = receipt.spans;
  return (
    <>
      <div className="well spans" style={{ marginTop: 12 }}>
        <div className="ph">
          <span>span tree — excerpt</span>
          {receipt.trace_id && <span>trace {receipt.trace_id}</span>}
        </div>
        {spans.map((sp, i) => {
          const depth = sp.depth ?? 0;
          const isLast = i === spans.length - 1;
          const tree = depth === 0 ? "" : "│  ".repeat(Math.max(0, depth - 1)) + (isLast ? "└─ " : "├─ ");
          const failed = sp.failed === true;
          return (
            <div key={i} className={cx("sprow", failed && "fail")}>
              {tree !== "" && <span className="tree">{tree}</span>}
              <span className="nm">{sp.name ?? ""}</span>
              {failed && <span className="badge500">✕ {sp.status ?? 500}</span>}
              <span className="ms">
                {sp.duration_ms !== null && sp.duration_ms !== undefined ? (
                  <>
                    <span className="num">{trimNum(sp.duration_ms)}</span> ms
                  </>
                ) : (
                  "— not reached"
                )}
              </span>
            </div>
          );
        })}
      </div>
      {receipt.dynatrace_link && (
        <div className="receiptrow" style={{ marginTop: 12 }}>
          <a className="go" href={receipt.dynatrace_link} target="_blank" rel="noreferrer">
            Open trace in Dynatrace →
          </a>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ timing ruler

export function TimingRuler({ receipt }: { receipt: TimingRulerReceipt }) {
  return (
    <>
      <div className="ruler">
        <span className="seg a" />
        <span className="seg b" />
        <span className="tick" />
        <span className="eye" />
        <svg
          className="fray"
          width="26"
          height="26"
          viewBox="0 0 26 26"
          style={{ left: "calc(64% - 25px)" }}
          fill="none"
          stroke="#E8A33D"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M0 13 C 5 12.8, 9 12.2, 12 10.6" />
          <path d="M1 13 C 7 13.2, 12 12.8, 17 13.6" />
          <path d="M2 13.4 C 6 14.4, 9 16.2, 11 18.6" />
        </svg>
        <svg
          className="fray"
          width="26"
          height="26"
          viewBox="0 0 26 26"
          style={{ left: "68.4%", transform: "translateX(-1px) scaleX(-1)" }}
          fill="none"
          stroke="#E8A33D"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M0 13 C 4 12.6, 7 11.6, 9 9.8" />
          <path d="M1 13 C 6 13.4, 10 14.2, 14 16.2" />
          <path d="M2 13 C 7 13, 11 12.6, 15 12.2" />
        </svg>
        <span className="gapline" />
        <span className="gaplabel num">
          {receipt.gap_s !== null ? `+${trimNum(receipt.gap_s)} s` : "—"}
        </span>
        <span className="lab" style={{ left: "22%" }}>
          deploy <span className="num">{shortSha(receipt.deploy_sha)}</span> ·{" "}
          <span className="num">{receipt.deploy_at ?? "—"}</span>
        </span>
        <span className="lab warn" style={{ left: "66.2%" }}>
          first failure · <span className="num">{receipt.first_failure_at ?? "—"}</span>
        </span>
      </div>
      {receipt.note && (
        <p className="cap" style={{ fontSize: 13.5, color: "var(--ink)" }}>
          {wrapNums(receipt.note)}
        </p>
      )}
    </>
  );
}

// ------------------------------------------------------------------ suspect hunk / proposed diff

export function SuspectHunk({
  receipt,
  deploySha,
}: {
  receipt: SuspectHunkReceipt;
  deploySha: string | null;
}) {
  const { addLines } = diffStats(receipt.diff);
  const blame = [...new Set([...addLines, ...captionLineRefs(receipt.caption)])];
  return (
    <>
      <DiffBlock
        path={receipt.path}
        meta={
          deploySha ? (
            <>
              commit <span className="num">{shortSha(deploySha)}</span>
            </>
          ) : undefined
        }
        diff={receipt.diff}
        blame={blame}
      />
      {receipt.caption && (
        <p className="cap" style={{ marginTop: 12 }}>
          {wrapNums(receipt.caption)}
        </p>
      )}
    </>
  );
}

export function ProposedDiff({
  receipt,
  branch,
}: {
  receipt: ProposedDiffReceipt;
  branch: string | null;
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <DiffBlock
        path={receipt.files[0] ?? ""}
        meta={
          branch ? (
            <>
              branch <span className="num">{branch}</span>
            </>
          ) : undefined
        }
        diff={receipt.diff}
      />
    </div>
  );
}

// ------------------------------------------------------------------ rationale / model meta

export function RationaleQuote({ receipt }: { receipt: RationaleReceipt }) {
  return <blockquote className="quote">&ldquo;{wrapNums(receipt.text)}&rdquo;</blockquote>;
}

export function ModelMetaLine({ receipt }: { receipt: ModelMetaReceipt }) {
  return (
    <div className="metaline">
      model <b>{receipt.model}</b> · tokens{" "}
      <b className="num">
        {groupedInt(receipt.tokens_in)} in / {groupedInt(receipt.tokens_out)} out
      </b>
      {receipt.cost_usd !== null && receipt.cost_usd !== undefined && (
        <>
          {" "}
          · cost <b className="num">{money(receipt.cost_usd)}</b>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ PR card

function checkNode(name: string, state: string, key: number): ReactNode {
  const s = state.toLowerCase();
  let mark: ReactNode;
  if (["success", "ok", "passed", "done", "✓"].includes(s)) {
    mark = <span className="num">✓</span>;
  } else if (["running", "in_progress", "pending", "queued"].includes(s)) {
    mark = <span className="run">— {s === "queued" ? "queued" : "running"}</span>;
  } else if (["failure", "failed", "error"].includes(s)) {
    mark = <span className="num">✕</span>;
  } else {
    mark = <span className="run">— {state}</span>;
  }
  return (
    <Fragment key={key}>
      {key > 0 && " · "}
      {name} {mark}
    </Fragment>
  );
}

export function PrCard({ receipt }: { receipt: PrReceipt }) {
  return (
    <>
      <div className="well pr">
        <div className="toprow">
          <span className="num">{receipt.repo}</span>
          <span className="branch num">{receipt.branch}</span>
        </div>
        <div className="title">
          <span className="id num">{receipt.number !== null ? `#${receipt.number}` : "—"}</span>
          <span className="id">—</span>
          <span className="t">{receipt.title}</span>
        </div>
        {receipt.toc.length > 0 && (
          <div className="toc">
            <div className="toclabel">dossier — table of contents</div>
            <ol>
              {receipt.toc.map((item, i) => (
                <li key={i}>
                  <span className="n num">{i + 1}</span>
                  <span>{wrapNums(item)}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {receipt.checks.length > 0 && (
          <div className="ci">{receipt.checks.map((c, i) => checkNode(c.name, c.state, i))}</div>
        )}
      </div>
      <div className="receiptrow">
        {receipt.url && (
          <a className="btn btn-ink btn-sm" href={receipt.url} target="_blank" rel="noreferrer">
            Open PR on GitHub →
          </a>
        )}
        <span className="cap">The PR body is the dossier. The receipts travel with the fix.</span>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ approval

export function ApprovalRows({ receipt }: { receipt: ApprovalReceipt }) {
  return (
    <>
      <div className="well">
        <div className="okrow">
          <span className="tickmark">✓</span>approved by {receipt.by} at{" "}
          <span className="num" style={{ fontWeight: 600 }}>
            {utcClock(receipt.at)}
          </span>
        </div>
        {receipt.deploy_line && (
          <div className="okrow">
            <span className="tickmark">✓</span>
            <span>{wrapNums(receipt.deploy_line, true)}</span>
          </div>
        )}
      </div>
      <p className="cap" style={{ marginTop: 14 }}>
        Darn never merges by itself. A human held the needle.
      </p>
    </>
  );
}

// ------------------------------------------------------------------ replay

export function ReplayGrid({ receipt }: { receipt: ReplayReceipt }) {
  return (
    <div className="replay">
      <div className="rp was">
        <div className="line num">
          {receipt.method} {receipt.path} → <span className="code5">{receipt.before_status ?? "—"}</span>
        </div>
        <div className="sub">
          the failing request · replayed <span className="num">{receipt.before_at ?? "—"}</span>
        </div>
      </div>
      <div className="rp now">
        <div className="line num">
          {receipt.method} {receipt.path} →{" "}
          <span style={{ fontWeight: 700 }}>{receipt.after_status ?? "—"}</span>
        </div>
        <div className="sub">
          the same request, re-sent · replayed <span className="num">{receipt.after_at ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ closure

export function ClosureCard({
  receipt,
  incident,
}: {
  receipt: ClosureReceipt;
  incident: Incident;
}) {
  const davis = findIncidentReceipt(incident, "davis_problem");
  const link = receipt.dynatrace_link ?? incident.problem_url;
  return (
    <div className="well davis">
      <div className="top">
        <span className="sev ok">
          <SevClosed />
        </span>
        <div>
          <div className="ttl">{davis?.title ?? incident.title}</div>
          <div className="sub">
            <span className="num">{receipt.problem_id || incident.problem_id}</span> · Closed{" "}
            <span className="num">{receipt.closed_at ?? "—"}</span>
          </div>
        </div>
        <span style={{ flex: 1 }} />
        <PillOk>Closed</PillOk>
      </div>
      <div className="receiptrow" style={{ margin: "14px 0 2px 46px" }}>
        {link && (
          <a className="go" href={link} target="_blank" rel="noreferrer">
            Open problem in Dynatrace →
          </a>
        )}
        <span className="cap">The referee says it&rsquo;s mended.</span>
      </div>
    </div>
  );
}

export function ReceiptListFooter({
  receipt,
  incident,
}: {
  receipt: ClosureReceipt;
  incident: Incident;
}) {
  return (
    <div className="receiptlist">
      closure comment posted to PR{" "}
      <span className="num">{incident.pr_number !== null ? `#${incident.pr_number}` : "—"}</span>{" "}
      <span className="num">{receipt.pr_comment_posted ? "✓" : "skipped"}</span>
      <span className="sep">·</span>deployment annotation sent (send_event){" "}
      <span className="num">{receipt.annotation_sent ? "✓" : "skipped"}</span>
      {receipt.notebook_url && (
        <>
          <span className="sep">·</span>
          <a href={receipt.notebook_url} target="_blank" rel="noreferrer">
            incident notebook →
          </a>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ wall clock summary

export function WallClockCard({ incident }: { incident: Incident }) {
  const w = incident.wall_clock_summary;
  if (!w) {
    return null;
  }
  const mm = (s: number | null) => {
    if (s === null) {
      return "—";
    }
    const total = Math.max(0, Math.floor(s));
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  };
  return (
    <div className="wallclock">
      <span className="item">
        detected → PR open <span className="num">{mm(w.detected_to_pr_s)}</span>
      </span>
      <span className="sep">·</span>
      <span className="item">
        approved → verified closed <span className="num">{mm(w.approved_to_verified_s)}</span>
      </span>
      <span className="sep">·</span>
      <span className="item">
        DQL receipts <span className="num">{w.dql_receipts}</span>
      </span>
      {w.token_cost_usd !== null && (
        <>
          <span className="sep">·</span>
          <span className="item">
            token cost <span className="num">{money(w.token_cost_usd)}</span>
          </span>
        </>
      )}
      <span className="note">All measured during this incident — never invented.</span>
    </div>
  );
}

// ------------------------------------------------------------------ knot (tied off)

export function KnotEvidence({ receipt }: { receipt: KnotReceipt }) {
  return (
    <>
      {receipt.evidence && <div className="well evwell">{wrapNums(receipt.evidence)}</div>}
      {receipt.reason && (
        <p className="cap" style={{ marginTop: 12 }}>
          {wrapNums(receipt.reason)}
        </p>
      )}
      <p className="stop">Darn stops here. No PR. No guessing.</p>
    </>
  );
}

// ------------------------------------------------------------------ note

export function NoteLine({ receipt }: { receipt: NoteReceipt }) {
  return (
    <p className="cap" style={{ marginTop: 16 }}>
      {wrapNums(receipt.text)}
    </p>
  );
}

// ------------------------------------------------------------------ group labels + the stream

function glabelFor(receipt: Receipt): string | null {
  switch (receipt.type) {
    case "dql": {
      const known: Record<string, string> = {
        numbers: "The numbers",
        exception: "The exception",
        recovery: "Recovery DQL",
      };
      return known[receipt.group] ?? (receipt.label || null);
    }
    case "timing_ruler":
      return "The timing";
    case "suspect_hunk":
      return "The suspect";
    case "replay":
      return "Replay receipt";
    case "closure":
      return "Davis closure";
    default:
      return null;
  }
}

export function GroupLabel({ children }: { children: ReactNode }) {
  return (
    <div className="glabel">
      <span className="stitch" />
      <span className="t">{children}</span>
    </div>
  );
}

export interface ReceiptStreamProps {
  stage: Stage;
  incident: Incident;
  /** Receipt types the surrounding stage layout renders itself. */
  skip?: Receipt["type"][];
}

/**
 * Renders a stage's receipts in order, emitting a group label (stitch + name)
 * whenever the group changes, pairing each dql with its dql_result.
 */
export function ReceiptStream({ stage, incident, skip = [] }: ReceiptStreamProps) {
  const receipts = stage.receipts;
  const consumed = new Set<string>();
  const deploySha =
    findReceipt(receipts, "timing_ruler")?.deploy_sha ?? incident.sabotage_sha ?? null;
  const branch = findIncidentReceipt(incident, "pr")?.branch ?? null;
  const nodes: ReactNode[] = [];
  let lastLabel: string | null = null;

  receipts.forEach((receipt, i) => {
    if (consumed.has(receipt.id) || skip.includes(receipt.type) || receipt.type === "dql_result") {
      return;
    }
    const label = glabelFor(receipt);
    if (label && label !== lastLabel) {
      nodes.push(<GroupLabel key={`g-${i}`}>{label}</GroupLabel>);
      lastLabel = label;
    }
    let node: ReactNode = null;
    switch (receipt.type) {
      case "davis_problem":
        node = <DavisProblemCard receipt={receipt} />;
        break;
      case "dql": {
        let result: DqlResultReceipt | null = null;
        const byId = receipts.find(
          (r): r is DqlResultReceipt => r.type === "dql_result" && r.for_query_id === receipt.id
        );
        const next = receipts[i + 1];
        if (byId) {
          result = byId;
        } else if (next && next.type === "dql_result" && !next.for_query_id) {
          result = next;
        }
        if (result) {
          consumed.add(result.id);
        }
        node =
          receipt.group === "recovery" ? (
            <RecoveryBlock receipt={receipt} result={result} />
          ) : (
            <DqlGroup receipt={receipt} result={result} />
          );
        break;
      }
      case "trace_excerpt":
        node = <TraceExcerpt receipt={receipt} />;
        break;
      case "timing_ruler":
        node = <TimingRuler receipt={receipt} />;
        break;
      case "suspect_hunk":
        node = <SuspectHunk receipt={receipt} deploySha={deploySha} />;
        break;
      case "proposed_diff":
        node = <ProposedDiff receipt={receipt} branch={branch} />;
        break;
      case "rationale":
        node = <RationaleQuote receipt={receipt} />;
        break;
      case "model_meta":
        node = <ModelMetaLine receipt={receipt} />;
        break;
      case "pr":
        node = <PrCard receipt={receipt} />;
        break;
      case "approval":
        node = <ApprovalRows receipt={receipt} />;
        break;
      case "replay":
        node = <ReplayGrid receipt={receipt} />;
        break;
      case "closure":
        node = <ClosureCard receipt={receipt} incident={incident} />;
        break;
      case "knot":
        node = <KnotEvidence receipt={receipt} />;
        break;
      case "note":
        node = <NoteLine receipt={receipt} />;
        break;
    }
    nodes.push(<Fragment key={receipt.id}>{node}</Fragment>);
  });

  return <>{nodes}</>;
}
