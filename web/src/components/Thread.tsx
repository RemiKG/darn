/**
 * The thread — Darn's signature stitch motif, one grammar
 * everywhere:
 *   pending  = faint dashed thread        (--ink-faint, dash 7 6)
 *   active   = amber dashed thread        (animated dash-offset in product)
 *   done     = solid ink thread
 *   breakage = an amber tear (gap with two frayed stub-strokes)
 *   tied off = the thread ends in a small knot
 *
 * Exports:
 *   HorizontalThread — the 6-node landing timeline (SVG)
 *   VerticalSpine    — the incident ledger's left lane (CSS grammar)
 *   WizardThread     — the 3-step /yours progress thread
 *   Knot             — the small knot icon
 *   Tear             — a standalone amber tear marker
 */

import type { CSSProperties } from "react";
import { cx } from "../lib/cx";

export type ThreadState = "pending" | "active" | "done";

// ------------------------------------------------------------- geometry

const VIEW_W = 1200;
const VIEW_H = 44;
const Y = 22;
const X_START = 24;
const X_END = 1176;
const NODE_FIRST = 100;
const NODE_LAST = 1100;

const INK = "#1B2A44";
const AMBER = "#E8A33D";
const FAINT = "rgba(27,42,68,.40)";
const CREAM = "#F5F3EF";
const DASH = "7 6";

type LineStyle = "done" | "active" | "pending";

interface Run {
  x1: number;
  x2: number;
  style: LineStyle;
}

/** Split runs around the tear gap [g0, g1]. */
function cutRuns(runs: Run[], g0: number, g1: number): Run[] {
  const out: Run[] = [];
  for (const r of runs) {
    if (r.x2 <= g0 || r.x1 >= g1) {
      out.push(r);
      continue;
    }
    if (r.x1 < g0) {
      out.push({ x1: r.x1, x2: g0, style: r.style });
    }
    if (r.x2 > g1) {
      out.push({ x1: g1, x2: r.x2, style: r.style });
    }
  }
  return out;
}

export interface ThreadLabel {
  name: string;
  /** Mono timestamp/elapsed shown once the stage is reached. */
  ts?: string | null;
}

export interface HorizontalThreadProps {
  /** One state per node, left to right (the landing timeline passes 6). */
  states: ThreadState[];
  /**
   * Node index at which the breakage tear is drawn (the amber tear sits on the
   * thread just before that node — the landing uses 0, the moment of sabotage).
   * Omit/null for no tear (idle).
   */
  tear?: number | null;
  /** Optional stage labels rendered in a grid under the thread. */
  labels?: ThreadLabel[];
  className?: string;
}

export function HorizontalThread({ states, tear = null, labels, className }: HorizontalThreadProps) {
  const n = states.length;
  const step = n > 1 ? (NODE_LAST - NODE_FIRST) / (n - 1) : 0;
  const nodeX = (i: number) => NODE_FIRST + step * i;

  const lastDone = states.lastIndexOf("done");
  const activeIdx = states.indexOf("active");
  const idle = lastDone < 0 && activeIdx < 0;

  // build the line runs
  let runs: Run[] = [];
  if (idle) {
    runs = [{ x1: X_START, x2: X_END, style: "pending" }];
  } else {
    const solidEnd = lastDone >= 0 ? nodeX(lastDone) : X_START;
    const amberEnd = activeIdx >= 0 ? nodeX(activeIdx) : solidEnd;
    const allDone = lastDone === n - 1;
    if (solidEnd > X_START) {
      runs.push({ x1: X_START, x2: solidEnd, style: "done" });
    }
    if (amberEnd > solidEnd) {
      runs.push({ x1: solidEnd, x2: amberEnd, style: "active" });
    }
    const tailStart = Math.max(solidEnd, amberEnd);
    if (tailStart < X_END) {
      runs.push({ x1: tailStart, x2: X_END, style: allDone ? "done" : "pending" });
    }
  }

  // the tear: a gap with two frayed stub-strokes, just before node `tear`
  let tearMark: { g0: number; g1: number } | null = null;
  if (tear !== null && tear >= 0 && tear < n && !idle) {
    const g1 = nodeX(tear) - 29;
    const g0 = nodeX(tear) - 51;
    tearMark = { g0, g1 };
    runs = cutRuns(runs, g0, g1);
  }

  const stroke = (s: LineStyle) => (s === "done" ? INK : s === "active" ? AMBER : FAINT);

  return (
    <div className={className}>
      <svg className="thread-svg" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} aria-hidden="true">
        {runs.map((r, i) => (
          <line
            key={i}
            x1={r.x1}
            y1={Y}
            x2={r.x2}
            y2={Y}
            stroke={stroke(r.style)}
            strokeWidth="2.5"
            strokeDasharray={r.style === "done" ? undefined : DASH}
            className={r.style === "active" ? "dash-anim" : undefined}
          />
        ))}
        {tearMark && (
          <g stroke={AMBER} strokeWidth="2.5" strokeLinecap="round" fill="none">
            <path d={`M${tearMark.g0} ${Y}c3.4-.7 5.4-2.6 6.4-5.4`} />
            <path d={`M${tearMark.g0 + 4} ${Y - 8.4}l3.2-2`} />
            <path d={`M${tearMark.g1} ${Y}c-3.4.7-5.4 2.6-6.4 5.4`} />
            <path d={`M${tearMark.g1 - 4} ${Y + 8.4}l-3.2 2`} />
          </g>
        )}
        {states.map((s, i) => {
          const x = nodeX(i);
          if (s === "done") {
            return <circle key={i} cx={x} cy={Y} r="7" fill={INK} />;
          }
          if (s === "active") {
            return (
              <g key={i}>
                <circle cx={x} cy={Y} r="11.5" fill="none" stroke="rgba(232,163,61,.35)" strokeWidth="3" />
                <circle cx={x} cy={Y} r="7" fill={AMBER} />
              </g>
            );
          }
          return <circle key={i} cx={x} cy={Y} r="6" fill={CREAM} stroke={FAINT} strokeWidth="2" />;
        })}
      </svg>
      {labels && (
        <div className="tstages" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>
          {labels.map((label, i) => (
            <div key={i} className={cx("tstage", states[i] === "done" && "done", states[i] === "active" && "active")}>
              {label.name}
              {label.ts ? <span className="ts num">{label.ts}</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------- vertical spine

export interface VerticalSpineProps {
  /** Stitch grammar for this stage's lane segment. */
  state?: ThreadState;
  /** First stage row: the thread starts at the node, not above it. */
  first?: boolean;
  /** Last stage row: the thread ends at the node. */
  last?: boolean;
  /** Tied off: the thread ends in a knot below the node (knot terminal variant). */
  knot?: boolean;
  /**
   * Vertical offset of the node/hang in px (default 28 — hangs the
   * node level with the stage-card header).
   */
  nodeTop?: number;
  className?: string;
}

/**
 * The incident ledger's left lane: drop one per `.stage` grid row
 * (`<section class="stage"><VerticalSpine …/><div class="body">…</div></section>`).
 * Same grammar as the landing thread, drawn vertically.
 */
export function VerticalSpine({ state = "done", first, last, knot, nodeTop, className }: VerticalSpineProps) {
  const nodeStyle: CSSProperties | undefined =
    nodeTop !== undefined ? { top: `${nodeTop}px` } : undefined;
  const hangStyle: CSSProperties | undefined =
    nodeTop !== undefined ? { top: `${nodeTop - 1.25}px` } : undefined;
  return (
    <div
      className={cx(
        "lane",
        state !== "done" && state,
        first && "first",
        last && "last",
        knot && "knotted",
        className
      )}
      aria-hidden="true"
    >
      <span className="hang" style={hangStyle} />
      <span className="node" style={nodeStyle} />
      {knot && <Knot className="knot" />}
    </div>
  );
}

// ------------------------------------------------------------- wizard thread

export interface WizardStep {
  label: string;
  state: ThreadState;
  /** Small uppercase mono caption under the label (e.g. "done"). */
  stateLabel?: string;
}

/** The 3-step stitched progress thread on /yours. */
export function WizardThread({ steps, className }: { steps: WizardStep[]; className?: string }) {
  return (
    <div className={cx("pthread", className)}>
      {steps.map((step, i) => (
        <div key={i} className={cx("pseg", step.state)}>
          <div className="pnode">{step.state === "done" ? "✓" : i + 1}</div>
          <div className="plabel">{step.label}</div>
          {step.stateLabel ? <div className="pstate">{step.stateLabel}</div> : null}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- knot & tear icons

/** The small knot — early termination, "tied off". */
export function Knot({ size = 36, className }: { size?: number; className?: string }) {
  const h = Math.round((size * 44) / 36);
  return (
    <svg
      className={className}
      width={size}
      height={h}
      viewBox="0 0 36 44"
      fill="none"
      stroke={INK}
      strokeWidth="2.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M18 0 V10" />
      <path d="M18 10 C 25.5 10, 30 14, 30 19 C 30 25, 24 28.5, 18 28.5 C 12 28.5, 6 25, 6 19 C 6 14.5, 10 10.8, 15 10.2" />
      <path d="M18 10 C 15.5 14, 15 19, 17 24 C 18.5 28, 21 33, 25 39" stroke={CREAM} strokeWidth="5.5" />
      <path d="M18 10 C 15.5 14, 15 19, 17 24 C 18.5 28, 21 33, 25 39" />
    </svg>
  );
}

/**
 * A standalone amber tear — the breakage mark: a gap in the thread with two
 * frayed stub-strokes curling away from it.
 */
export function Tear({ width = 60, className }: { width?: number; className?: string }) {
  const h = Math.round((width * 44) / 60);
  return (
    <svg
      className={className}
      width={width}
      height={h}
      viewBox="0 0 60 44"
      fill="none"
      stroke={AMBER}
      strokeWidth="2.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <line x1="4" y1="22" x2="18" y2="22" />
      <path d="M18 22c3.4-.7 5.4-2.6 6.4-5.4" />
      <path d="M22 13.6l3.2-2" />
      <line x1="42" y1="22" x2="56" y2="22" />
      <path d="M42 22c-3.4.7-5.4 2.6-6.4 5.4" />
      <path d="M38 30.4l-3.2 2" />
    </svg>
  );
}
