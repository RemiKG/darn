/**
 * DQL receipt block — dark --ink panel, JetBrains Mono 12.5px, amber keyword
 * highlighting, and a copy button labeled "Copy — re-run this yourself"
 * (or plain "Copy" in the compact variant). Optionally renders the result
 * table (mono, hairline rows) beneath it.
 */

import type { ReactNode } from "react";
import { cx } from "../lib/cx";
import CopyButton from "./CopyButton";

const KEYWORD_RE =
  /\b(fetch|filter|summarize|sort|fieldsAdd|timeseries|count|limit|by)\b|from:/g;

function highlight(query: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of query.matchAll(KEYWORD_RE)) {
    const start = match.index ?? 0;
    if (start > last) {
      out.push(query.slice(last, start));
    }
    out.push(
      <span key={key++} className="kw">
        {match[0]}
      </span>
    );
    last = start + match[0].length;
  }
  if (last < query.length) {
    out.push(query.slice(last));
  }
  return out;
}

export interface DqlResultTable {
  columns: string[];
  rows: (string | number | boolean | null)[][];
}

export interface DqlBlockProps {
  /** The DQL text, verbatim — what the copy button copies. */
  query: string;
  /** Compact variant: shorter copy-button label, tighter padding. */
  compact?: boolean;
  /** Override the copy-button label. */
  copyLabel?: string;
  /** Optional result table rendered under the panel. */
  result?: DqlResultTable | null;
  /** Index of a result row to amber-wash (the "hot" row). */
  hotRow?: number;
  className?: string;
}

function isNumericColumn(rows: (string | number | boolean | null)[][], col: number): boolean {
  let seen = false;
  for (const row of rows) {
    const v = row[col];
    if (v === null || v === undefined || v === "") {
      continue;
    }
    if (typeof v !== "number") {
      return false;
    }
    seen = true;
  }
  return seen;
}

export default function DqlBlock({
  query,
  compact,
  copyLabel,
  result,
  hotRow,
  className,
}: DqlBlockProps) {
  const label = copyLabel ?? (compact ? "Copy" : "Copy — re-run this yourself");
  const numeric = result ? result.columns.map((_, i) => isNumericColumn(result.rows, i)) : [];
  return (
    <div className={className}>
      <div className={cx("dqlwrap", compact && "tight")}>
        <div className="dql">{highlight(query)}</div>
        <CopyButton text={query} label={label} aria-label="Copy this DQL query" />
      </div>
      {result && (
        <table className="rtable">
          <thead>
            <tr>
              {result.columns.map((col, i) => (
                <th key={i} className={numeric[i] ? "r" : undefined}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, ri) => (
              <tr key={ri} className={ri === hotRow ? "hot" : undefined}>
                {row.map((cell, ci) => (
                  <td key={ci} className={numeric[ci] ? "r" : undefined}>
                    {cell === null || cell === undefined ? "—" : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
