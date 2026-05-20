/**
 * Step 3 — Map services: the mapping body.
 * Left panel lists the monitored services discovered live from the tenant;
 * right panel shows the repo from step 2; map rows pair service → repo with a
 * Watch toggle; the DEPLOY MARKERS panel (essential) carries the copyable curl
 * snippet; "Start watching" posts the mappings.
 *
 * Used by the wizard's step 3 card AND by the connected state's
 * "+ Add a service" card (Yours.tsx owns the state either way).
 */

import CopyButton from "../CopyButton";
import { BtnAmber } from "../Buttons";
import { cx } from "../../lib/cx";

/** Deployment-marker snippet. */
export const DEPLOY_MARKER_SNIPPET = `curl -X POST "$DT_TENANT/platform/classic/environment-api/v2/events/ingest" \\
  -H "Authorization: Api-Token $DT_TOKEN" \\
  -d '{"eventType":"CUSTOM_DEPLOYMENT","title":"deploy '"$GIT_SHA"'", ...}'`;

export interface MapRow {
  service: string;
  health?: string | null;
  repo: string;
  watch: boolean;
}

export function healthAmber(health: string | null | undefined): boolean {
  return !!health && health !== "ok" && health !== "healthy";
}

export interface MapServicesProps {
  rows: MapRow[];
  onRows: (rows: MapRow[]) => void;
  /** Repo from step 2 ("" until the GitHub App reports an install). */
  repo: string;
  /** Default branch shown (and posted) — "" renders the honest dash. */
  branch: string;
  /** False = read-only preview (GitHub App not installed/configured). */
  canMap: boolean;
  busy: boolean;
  onStart: () => void;
  error?: string | null;
}

export default function MapServices({
  rows,
  onRows,
  repo,
  branch,
  canMap,
  busy,
  onStart,
  error,
}: MapServicesProps) {
  const setRow = (i: number, patch: Partial<MapRow>) => {
    onRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  };
  const startDisabled = busy || !canMap || !rows.some((r) => r.repo);

  return (
    <>
      <div className="map3">
        <div className="panel">
          <h3>Monitored services — from your tenant</h3>
          {rows.map((r) => (
            <div className="svc" key={r.service}>
              <span className={cx("dot", healthAmber(r.health) && "amber")} />
              {r.service}
            </div>
          ))}
        </div>
        <div className="panel">
          <h3>Repo — from step 2</h3>
          <div className="kv">
            <span className="k">Repo</span>
            <span className={cx("v", !repo && "faint")}>{repo || "—"}</span>
          </div>
          <div className="kv">
            <span className="k">Default branch</span>
            <span className={cx("v", !branch && "faint")}>{branch || "—"}</span>
          </div>
        </div>
      </div>

      <div className="maprows">
        {rows.map((r, i) => (
          <div className="maprow" key={r.service}>
            <span className="svcname">
              <span className={cx("dot", healthAmber(r.health) && "amber")} />
              {r.service}
            </span>
            <span className="arrow">→</span>
            <span className="selwrap">
              <select
                className={r.repo ? undefined : "empty"}
                value={r.repo}
                disabled={!canMap}
                aria-label={`Repo for ${r.service}`}
                onChange={(e) =>
                  setRow(i, {
                    repo: e.target.value,
                    watch: e.target.value ? r.watch : false,
                  })
                }
              >
                <option value="">select repo</option>
                {repo ? <option value={repo}>{repo}</option> : null}
              </select>
              <span className="caret">▾</span>
            </span>
            <button
              type="button"
              className={cx("watch", !r.watch && "off")}
              role="switch"
              aria-checked={r.watch}
              disabled={!canMap || !r.repo}
              onClick={() => setRow(i, { watch: !r.watch })}
            >
              Watch <span className={cx("tgl", r.watch ? "on" : "off")} />
            </button>
          </div>
        ))}
      </div>

      <div className="well-amber">
        <p className="lead">
          Darn pins blame by intersecting failure onset with deploy events. Ship a deployment
          marker from your CI:
        </p>
        <div className="snippet">
          <div className="dql">{DEPLOY_MARKER_SNIPPET}</div>
          <CopyButton text={DEPLOY_MARKER_SNIPPET} label="Copy" noIcon aria-label="Copy the deployment marker snippet" />
        </div>
        <p className="cap">
          No markers? Darn falls back to commit timestamps on the default branch — blame gets
          slower and softer, and the PR says so.
        </p>
      </div>

      {error ? (
        <div className="errrow">
          <span className="msg">{error}</span>
        </div>
      ) : null}

      <div className="endrow">
        <BtnAmber onClick={onStart} disabled={startDisabled}>
          {busy ? "Starting…" : "Start watching"}
        </BtnAmber>
      </div>
    </>
  );
}
