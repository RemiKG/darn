/**
 * Diff block — brand diff colors only: removed lines amber-wash
 * with "−", added lines soft navy wash rgba(27,42,68,.08) with "+". No red,
 * no green. JetBrains Mono, file-path header, parses a unified-diff string.
 */

import type { ReactNode } from "react";
import { cx } from "../lib/cx";

interface DiffRow {
  kind: "hunk" | "context" | "add" | "rem";
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function parseUnifiedDiff(diff: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.replace(/\r\n/g, "\n").split("\n")) {
    const hunk = HUNK_RE.exec(raw);
    if (hunk) {
      oldNo = parseInt(hunk[1], 10);
      newNo = parseInt(hunk[2], 10);
      rows.push({ kind: "hunk", text: raw, oldNo: null, newNo: null });
      continue;
    }
    if (
      raw.startsWith("diff ") ||
      raw.startsWith("index ") ||
      raw.startsWith("--- ") ||
      raw.startsWith("+++ ") ||
      raw.startsWith("\\ No newline")
    ) {
      continue; // file headers — the path renders in .dhead instead
    }
    if (raw.startsWith("-")) {
      rows.push({ kind: "rem", text: raw.slice(1), oldNo: oldNo++, newNo: null });
    } else if (raw.startsWith("+")) {
      rows.push({ kind: "add", text: raw.slice(1), oldNo: null, newNo: newNo++ });
    } else if (raw.length > 0 || rows.length > 0) {
      // context line (leading space optional in stored diffs)
      const text = raw.startsWith(" ") ? raw.slice(1) : raw;
      rows.push({ kind: "context", text, oldNo: oldNo++, newNo: newNo++ });
    }
  }
  // drop a single trailing blank context row from the final newline split
  const lastRow = rows[rows.length - 1];
  if (lastRow && lastRow.kind === "context" && lastRow.text === "") {
    rows.pop();
  }
  return rows;
}

export interface DiffBlockProps {
  /** File path shown in the header (mono). */
  path: string;
  /** Right-aligned header meta, e.g. <>commit <span className="num">4f2c91d</span></>. */
  meta?: ReactNode;
  /** Unified-diff text (hunk headers + -/+/context lines). */
  diff: string;
  /** NEW-side line numbers to mark with the amber blame stitch. */
  blame?: number[];
  className?: string;
}

export default function DiffBlock({ path, meta, diff, blame, className }: DiffBlockProps) {
  const rows = parseUnifiedDiff(diff);
  const blamed = new Set(blame ?? []);
  return (
    <div className={cx("diff", className)}>
      <div className="dhead">
        <span>{path}</span>
        {meta !== undefined && <span className="right">{meta}</span>}
      </div>
      {rows.map((row, i) => {
        if (row.kind === "hunk") {
          return (
            <div key={i} className="dline hunk">
              <span className="code">{row.text}</span>
            </div>
          );
        }
        const isBlame = row.newNo !== null && blamed.has(row.newNo);
        return (
          <div
            key={i}
            className={cx(
              "dline",
              row.kind === "rem" && "rem",
              row.kind === "add" && "add",
              isBlame && "blame"
            )}
          >
            <span className="no old">{row.oldNo ?? ""}</span>
            <span className="no new">{row.newNo ?? ""}</span>
            <span className="sign">{row.kind === "rem" ? "−" : row.kind === "add" ? "+" : ""}</span>
            <span className="code">{row.text}</span>
          </div>
        );
      })}
    </div>
  );
}
