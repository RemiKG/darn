/**
 * Connected state — "Your watch".
 * Cards-as-rows table: service · tenant short host · repo · last problem seen ·
 * PRs opened · status pill · Pause / Unmap; "+ Add a service" re-opens the
 * mapping card; "Your mends" strip beneath (same card pattern as the landing's
 * Mended, kind=byo → /incident/{id}); empty state when nothing is watched.
 *
 * API gap, worked around here: ServiceMapping carries `prs_opened` as a
 * COUNT only — the individual PR links are derived from the mends whose title
 * names the service (never invented; if no mend is known, only the count shows).
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { IncidentSummary, ServiceMapping, YoursState } from "../../lib/api";
import { mmss, relTime } from "../../lib/format";
import Card from "../Card";
import EmptyState from "../EmptyState";
import { BtnGhost } from "../Buttons";
import { cx } from "../../lib/cx";
import MapServices, { type MapRow } from "./MapServices";

function shortHost(host: string): string {
  return host ? host.split(".")[0] : "—";
}

function prLinksFor(service: string, mends: IncidentSummary[]): { n: number; url: string }[] {
  return mends
    .filter((m) => m.pr_number !== null && m.title.includes(service))
    .map((m) => ({ n: m.pr_number as number, url: `https://github.com/${m.repo}/pull/${m.pr_number}` }));
}

function WatchRow({
  m,
  tenantHost,
  mends,
  busy,
  onPause,
  onUnmap,
}: {
  m: ServiceMapping;
  tenantHost: string;
  mends: IncidentSummary[];
  busy: boolean;
  onPause: () => void;
  onUnmap: () => void;
}) {
  const paused = m.paused || !m.watch;
  const links = prLinksFor(m.service, mends);
  const agoS = m.last_problem_at === null ? null : Date.now() / 1000 - m.last_problem_at;
  return (
    <Card className="trow">
      <span className="mono">{m.service}</span>
      <span className="mono">{shortHost(tenantHost)}</span>
      <span className="repo">{m.repo}</span>
      <span className={cx("mono", agoS === null && "faint")}>{agoS === null ? "—" : relTime(agoS)}</span>
      <span className={cx("prs", m.prs_opened === 0 && "faint")}>
        {m.prs_opened}
        {m.prs_opened > 0 && links.length > 0 ? (
          <>
            {" —"}
            {links.map((l) => (
              <a key={l.n} href={l.url} target="_blank" rel="noreferrer">
                #{l.n}
              </a>
            ))}
          </>
        ) : null}
      </span>
      <span>
        <span className={cx("pill", paused ? "pill-neutral" : "pill-ok", "pill-watch")}>
          ● {paused ? "Paused" : "Watching"}
        </span>
      </span>
      <span className="rowacts">
        <BtnGhost className="btn-xs" disabled={busy} onClick={onPause}>
          Pause
        </BtnGhost>
        <BtnGhost className="btn-xs" disabled={busy} onClick={onUnmap}>
          Unmap
        </BtnGhost>
      </span>
    </Card>
  );
}

export interface WatchViewProps {
  yours: YoursState;
  onPause: (service: string) => Promise<void>;
  onUnmap: (service: string) => Promise<void>;
  /** Posts the new mappings (rows with a repo chosen), then refreshes. */
  onAddMappings: (rows: MapRow[]) => Promise<void>;
}

export default function WatchView({ yours, onPause, onUnmap, onAddMappings }: WatchViewProps) {
  const [busyService, setBusyService] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [addRows, setAddRows] = useState<MapRow[]>([]);
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const mapped = useMemo(() => new Set(yours.mappings.map((m) => m.service)), [yours.mappings]);
  const unmapped = useMemo(
    () => yours.services.filter((s) => !mapped.has(s.name)),
    [yours.services, mapped]
  );

  const act = (service: string, fn: (s: string) => Promise<void>) => {
    setBusyService(service);
    void fn(service).finally(() => setBusyService(null));
  };

  const openAdd = () => {
    setAddRows(unmapped.map((s) => ({ service: s.name, health: s.health, repo: "", watch: false })));
    setAddError(null);
    setAddOpen(true);
  };

  const startAdd = () => {
    setAddBusy(true);
    setAddError(null);
    onAddMappings(addRows.filter((r) => r.repo))
      .then(() => setAddOpen(false))
      .catch((e: unknown) => setAddError(e instanceof Error ? e.message : String(e)))
      .finally(() => setAddBusy(false));
  };

  return (
    <>
      <div className="yourhead">
        <h2>Your watch.</h2>
      </div>

      {yours.mappings.length === 0 ? (
        <EmptyState size={200}>
          Nothing under watch yet. Three steps and Darn starts earning its keep.
        </EmptyState>
      ) : (
        <div className="watchgrid">
          <div className="thead">
            <span>Service</span>
            <span>Tenant</span>
            <span>Repo</span>
            <span>Last problem</span>
            <span>PRs opened</span>
            <span>Status</span>
            <span />
          </div>
          {yours.mappings.map((m) => (
            <WatchRow
              key={m.service}
              m={m}
              tenantHost={yours.tenant_host}
              mends={yours.mends}
              busy={busyService === m.service}
              onPause={() => act(m.service, onPause)}
              onUnmap={() => act(m.service, onUnmap)}
            />
          ))}
        </div>
      )}

      <button type="button" className="addrow" onClick={addOpen ? () => setAddOpen(false) : openAdd}>
        + Add a service
      </button>

      {addOpen ? (
        <Card className="mapcard">
          <MapServices
            rows={addRows}
            onRows={setAddRows}
            repo={yours.github.repo}
            branch={yours.github.installed ? "main" : ""}
            canMap={yours.github.installed && !!yours.github.repo}
            busy={addBusy}
            onStart={startAdd}
            error={addError}
          />
        </Card>
      ) : null}

      {yours.mends.length > 0 ? (
        <>
          <h3 className="mendshead">Your mends</h3>
          <div className="mends">
            {yours.mends.map((mend) => (
              <Card className="mend" key={mend.id}>
                <div className="t">{mend.title}</div>
                <div className="when">detected → closed {mmss(mend.detected_to_closed_s)}</div>
                <div className="row">
                  {mend.pr_number !== null ? (
                    <a
                      className="pr"
                      href={`https://github.com/${mend.repo}/pull/${mend.pr_number}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      PR #{mend.pr_number}
                    </a>
                  ) : (
                    <span className="pr">—</span>
                  )}
                  <Link className="rcpt" to={`/incident/${mend.id}`}>
                    receipts →
                  </Link>
                </div>
              </Card>
            ))}
          </div>
        </>
      ) : null}
    </>
  );
}
