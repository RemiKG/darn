/**
 * The medic's heartbeat — right-side drawer on the incident view.
 * 480px card surface over a 20% ink backdrop;
 * one mono waterfall row per agent step, bar lengths proportional to
 * measured seconds (ink bars, the Gemini row amber); totals row; the
 * agent-trace deep link ONLY when a real trace URL exists — otherwise a
 * calm honest line, never a fake.
 */

import { useEffect, useState } from "react";
import { api, type MedicRow, type MedicTrace } from "../lib/api";
import { groupedInt, money } from "../lib/format";
import { cx } from "../lib/cx";
import "../styles/pages/incident.css";

export interface HeartbeatDrawerProps {
  incidentId: string;
  /** Live medic trace from useIncident; the drawer fetches once if absent. */
  medic: MedicTrace | null;
  onClose: () => void;
}

function trim1(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
}

function rowLabel(row: MedicRow) {
  return (
    <span className="lbl">
      {row.tool}
      {row.calls > 1 && (
        <>
          {" "}
          ×<span className="num">{row.calls}</span>
        </>
      )}
    </span>
  );
}

function rowDuration(row: MedicRow) {
  const hasTokens =
    row.tokens_in !== null &&
    row.tokens_in !== undefined &&
    row.tokens_out !== null &&
    row.tokens_out !== undefined;
  return (
    <span className="dur">
      <span className="num">{row.seconds.toFixed(1)} s</span>
      {hasTokens && (
        <span className="toks">
          {" "}
          · <span className="num">{groupedInt(row.tokens_in)}</span> in /{" "}
          <span className="num">{groupedInt(row.tokens_out)}</span> out
        </span>
      )}
    </span>
  );
}

export default function HeartbeatDrawer({ incidentId, medic, onClose }: HeartbeatDrawerProps) {
  const [fetched, setFetched] = useState<MedicTrace | null>(null);
  const data = medic ?? fetched;

  useEffect(() => {
    if (!medic) {
      let stale = false;
      api
        .getMedic(incidentId)
        .then((m) => {
          if (!stale) {
            setFetched(m);
          }
        })
        .catch(() => {
          /* the drawer shows the honest empty state */
        });
      return () => {
        stale = true;
      };
    }
  }, [incidentId, medic]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = data?.rows ?? [];
  const total = data && data.wall_s > 0 ? data.wall_s : rows.reduce((s, r) => s + r.seconds, 0);

  // sequential waterfall: each bar starts where the previous one ended
  let cursor = 0;
  const bars = rows.map((row) => {
    const left = total > 0 ? (cursor / total) * 100 : 0;
    const width = total > 0 ? (row.seconds / total) * 100 : 0;
    cursor += row.seconds;
    return { left, width };
  });

  const ticks = total > 0 ? [0, 0.25, 0.5, 0.75, 1].map((f) => f * total) : [];

  return (
    <>
      <div className="hb-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="hb-drawer" role="dialog" aria-modal="true" aria-label="The medic's heartbeat">
        <div className="dhead">
          <h2>The medic&rsquo;s heartbeat</h2>
          <button type="button" className="xbtn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {/* ECG as running stitch */}
        <svg className="ecg" viewBox="0 0 416 24" preserveAspectRatio="none" aria-hidden="true">
          <path
            d="M2 13 H76 q9 -7 18 0 H126 l8 4 8 -15 8 20 8 -9 H188 q13 -8 26 0 H414"
            fill="none"
            stroke="var(--amber)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray="6 4"
          />
        </svg>

        <p className="dsub">Darn&rsquo;s own trace for this incident — same tenant, same scrutiny.</p>

        <div className="wf">
          <div className="eyebrow">Stage waterfall</div>
          {rows.length === 0 ? (
            <p className="dsub">Nothing measured yet — the heartbeat appears as the medic works.</p>
          ) : (
            <>
              {rows.map((row, i) => (
                <div key={i} className="wf-row">
                  <div className="wf-top">
                    {rowLabel(row)}
                    {rowDuration(row)}
                  </div>
                  <div className="wf-track">
                    <span
                      className={cx("wf-bar", row.kind === "gemini" && "amber")}
                      style={{ left: `${bars[i].left}%`, width: `${Math.max(bars[i].width, 1)}%` }}
                    />
                  </div>
                </div>
              ))}
              {ticks.length > 0 && (
                <div className="wf-axis">
                  {ticks.map((t, i) => (
                    <span key={i} className="num" style={{ left: `${i * 25}%` }}>
                      {trim1(t)} s
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {data && (
          <div className="totals">
            <span>
              tokens <span className="num">{groupedInt(data.tokens)}</span>
            </span>
            {data.cost_usd !== null && (
              <>
                <span className="sep">·</span>
                <span>
                  cost <span className="num">{money(data.cost_usd)}</span>
                </span>
              </>
            )}
            <span className="sep">·</span>
            <span>
              agent wall clock <span className="num">{data.wall_s.toFixed(1)} s</span>
            </span>
          </div>
        )}

        {data?.trace_url ? (
          <a className="btn btn-ink trace-btn" href={data.trace_url} target="_blank" rel="noreferrer">
            Open the agent&rsquo;s trace in Dynatrace →
          </a>
        ) : (
          <p className="notrace">agent traces aren&rsquo;t shipping on this deployment</p>
        )}

        <p className="dfoot">The medic wears the same heart monitor as the patient.</p>
      </aside>
    </>
  );
}
