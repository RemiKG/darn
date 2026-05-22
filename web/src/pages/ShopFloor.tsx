/**
 * The shop floor — route "/".
 * Landing + demo path: hero with the live health card, the sabotage menu,
 * the stitched timeline, receipts row, medic teaser, mended strip, the
 * honesty block and the BYO band. Every live numeral is mono and only ever
 * comes from the API — unavailable values render the honest dash, never a
 * placeholder.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Link, useLocation } from "react-router-dom";
import {
  api,
  ApiError,
  type AppStateSnapshot,
  type DavisProblemReceipt,
  type DefectKey,
  type DqlReceipt,
  type HealthCard,
  type Incident,
  type IncidentSummary,
  type PrReceipt,
} from "../lib/api";
import { honestDash, mmss, relTime, shortSha, utcClock } from "../lib/format";
import { useAppState, useCountdown, useElapsed } from "../lib/store";
import { cx } from "../lib/cx";
import { BtnAmber, BtnGhost, BtnInk, BtnOnInk } from "../components/Buttons";
import Card from "../components/Card";
import DqlBlock from "../components/DqlBlock";
import { PillAmber, PillOk } from "../components/Pills";
import HealthSpark from "../components/shopfloor/HealthSpark";
import { HorizontalThread, type ThreadLabel, type ThreadState } from "../components/Thread";
import Wordmark from "../components/Wordmark";
import "../styles/pages/shopfloor.css";

// ------------------------------------------------------------------ helpers

/** 0.31 → "0.31", 14.2 → "14.2" (value part only — unit renders separately). */
function pctValue(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) {
    return honestDash;
  }
  return v.toFixed(Math.abs(v) < 1 ? 2 : 1);
}

function intValue(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) {
    return honestDash;
  }
  return String(Math.round(v));
}

/** "The checkout null" → "the checkout null" (mono-line register). */
function lcFirst(s: string): string {
  return s ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

/** "https://github.com/remikg/loose-threads" → "github.com/remikg/loose-threads" */
function bareUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function prUrl(repo: string, prNumber: number): string {
  return `https://github.com/${repo}/pull/${prNumber}`;
}

/** CI check state → mono grammar ("build ✓ · deploy — running"). */
function checkMark(state: string): string {
  const v = state.toLowerCase();
  if (["success", "passed", "ok", "done", "completed", "✓"].includes(v)) {
    return "✓";
  }
  if (["running", "pending", "in_progress", "queued"].includes(v)) {
    return "— running";
  }
  return state;
}

const STAGE_NAMES = ["Detected", "Diagnosed", "Fix written", "PR open", "Approved", "Verified closed"];

// ------------------------------------------------------------------ (b) health card

function SockGlyph() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="#1B2A44"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M7.9 2.8h6.6v8.1c0 .9.4 1.75 1.1 2.33l2.7 2.2a3.5 3.5 0 0 1-4.4 5.44l-5.5-4.4A4.3 4.3 0 0 1 7.9 13Z" />
      <path d="M7.9 6.2h6.6" />
    </svg>
  );
}

function HealthStat({
  value,
  unit,
  label,
  labelMono,
  warn,
}: {
  value: string;
  unit?: string;
  label: string;
  labelMono?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="stat">
      {/* keyed remount = the numeral ticks (content swap), never fades */}
      <div key={value} className={cx("v", "num", warn && "warn")}>
        {value}
        {unit && value !== honestDash ? <span className="u"> {unit}</span> : null}
      </div>
      <div className={cx("l", labelMono && "num")}>{label}</div>
    </div>
  );
}

function HealthCardView({ health, tenantUrl }: { health: HealthCard | null; tenantUrl: string }) {
  // subtle stitch tick on the card's top border whenever a health refresh lands
  const [stitching, setStitching] = useState(false);
  const seen = useRef(false);
  useEffect(() => {
    if (!health) {
      return;
    }
    if (!seen.current) {
      seen.current = true;
      return;
    }
    setStitching(true);
    const t = setTimeout(() => setStitching(false), 950);
    return () => clearTimeout(t);
  }, [health]);

  const unavailable = !health || health.status === "unavailable";
  const torn = health?.status === "torn";

  return (
    <aside className="card health">
      <span className={cx("tick", stitching && "stitching")} aria-hidden="true" />
      <div className="hh">
        <SockGlyph />
        <span className="name">Loose Threads</span>
        <span className="right">
          <span className="livedot">
            <i />
            live
          </span>
          {health?.status === "ok" && <PillOk>All stitched</PillOk>}
          {torn && <PillAmber>Torn</PillAmber>}
        </span>
      </div>
      <div className="stats">
        <HealthStat
          value={unavailable ? honestDash : pctValue(health.error_rate)}
          unit="%"
          label="error rate"
          warn={torn}
        />
        <HealthStat value={unavailable ? honestDash : intValue(health.p95_ms)} unit="ms" label="p95" labelMono />
        <HealthStat value={unavailable ? honestDash : intValue(health.rpm)} label="req/min" />
      </div>
      {unavailable && (
        <p className="hwhy">{health?.reason || "telemetry not connected on this deployment"}</p>
      )}
      <div className="sparkhead">
        <span>synthetic shoppers</span>
      </div>
      <HealthSpark points={health?.sparkline ?? []} />
      <div className="hfoot">
        <span className="meta num">
          last deploy {shortSha(health?.last_deploy_sha)} · {relTime(health?.last_deploy_ago_s)}
        </span>
        {tenantUrl ? (
          <a href={tenantUrl} target="_blank" rel="noreferrer">
            Open in Dynatrace →
          </a>
        ) : null}
      </div>
    </aside>
  );
}

// ------------------------------------------------------------------ (c) defect menu

interface DefectDef {
  key: DefectKey;
  icon: string;
  name: string;
  blurb: string;
  davis: string;
}

const DEFECTS: DefectDef[] = [
  {
    key: "checkout-null",
    icon: "defect-checkout-null",
    name: "The checkout null",
    blurb: "Checkout forgets that carts can be empty. Nulls everywhere.",
    davis: "error-rate spike on POST /api/checkout",
  },
  {
    key: "catalog-stampede",
    icon: "defect-catalog-stampede",
    name: "The catalog stampede",
    blurb: "Every sock on the catalog page asks the database how it's feeling. Individually.",
    davis: "response-time degradation on GET /api/catalog",
  },
  {
    key: "penny-shaver",
    icon: "defect-penny-shaver",
    name: "The penny shaver",
    blurb: "Totals drift by a cent — and the payment provider rejects them.",
    davis: "error-rate spike on POST /api/pay",
  },
  {
    key: "inventory-grenade",
    icon: "defect-inventory-grenade",
    name: "The inventory grenade",
    blurb: "Restock math throws; nobody catches.",
    davis: "failure-rate spike on POST /api/inventory",
  },
];

function DefectCard({
  defect,
  selected,
  disabled,
  onSelect,
}: {
  defect: DefectDef;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (!disabled) {
        onSelect();
      }
    }
  };
  return (
    <div
      className={cx("card", "defect", selected && "sel")}
      role="radio"
      aria-checked={selected}
      aria-disabled={disabled || undefined}
      tabIndex={0}
      onClick={disabled ? undefined : onSelect}
      onKeyDown={onKeyDown}
    >
      <span className="radio" aria-hidden="true" />
      <svg className="icon" width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <use href={`/art/defect-icons.svg#${defect.icon}`} />
      </svg>
      <div className="dn">{defect.name}</div>
      <div className="dd">{defect.blurb}</div>
      <div className="davis">
        <b>Davis will see:</b> {defect.davis}
      </div>
    </div>
  );
}

const MISSING_NAMES: Record<string, string> = {
  github: "GitHub",
  dynatrace: "Dynatrace",
};

function TearSection({
  state,
  liveIncident,
  reload,
  mendRef,
}: {
  state: AppStateSnapshot | null;
  liveIncident: Incident | null;
  reload: () => void;
  mendRef: RefObject<HTMLElement>;
}) {
  const [selected, setSelected] = useState<DefectKey | null>(null);
  const [tornId, setTornId] = useState<string | null>(null);
  const [shipping, setShipping] = useState(false);
  const [missing, setMissing] = useState<string[] | null>(null);

  const liveId = state?.live_incident_id ?? null;
  const cooldownLeft = useCountdown(state?.cooldown_until ?? null);
  const liveElapsed = useElapsed(liveIncident?.started_at ?? null);

  // once my tear's incident has closed and the cooldown starts, drop back
  // into the normal flow (the cooldown banner takes over)
  useEffect(() => {
    if (tornId && !liveId && cooldownLeft !== null && cooldownLeft > 0) {
      setTornId(null);
    }
  }, [tornId, liveId, cooldownLeft]);

  const scrollToMend = useCallback(() => {
    mendRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [mendRef]);

  const onShip = async () => {
    if (!selected || shipping) {
      return;
    }
    setShipping(true);
    try {
      const res = await api.tear(selected);
      setTornId(res.incident_id);
      scrollToMend();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === "not_configured") {
          const body = e.body as { missing?: string[] };
          setMissing(body.missing ?? []);
        } else {
          // locked / cooldown: re-pull the snapshot — those banners render from state
          reload();
        }
      }
    } finally {
      setShipping(false);
    }
  };

  const repoUrl = state?.repo_url || "";
  const spectating = liveId !== null && tornId !== liveId;
  const cooling = !spectating && tornId === null && cooldownLeft !== null && cooldownLeft > 0;

  // mono progress row: real stage-0 receipts only (notes stream in over SSE)
  let progress: ReactNode = null;
  if (tornId) {
    const stage0 = liveIncident && liveIncident.id === tornId ? liveIncident.stages[0] : null;
    const notes = (stage0?.receipts ?? [])
      .filter((r) => r.type === "note")
      .map((r) => (r.type === "note" ? r.text : ""))
      .filter(Boolean);
    progress = (
      <div className="shipprog num" aria-live="polite">
        <i className="pdot" aria-hidden="true" />
        {notes.length > 0 ? <span key={notes.length}>{notes.join(" · ")}</span> : null}
      </div>
    );
  }

  let body: ReactNode;
  if (spectating) {
    const watchTo = `/incident/${liveId}`;
    body = (
      <div className="spectator">
        <h3>Someone's already torn a hole.</h3>
        {liveIncident && (
          <div className="stageline num">
            {lcFirst(liveIncident.title)} · stage {liveIncident.stage_index + 1} of 6 · {mmss(liveElapsed)}
          </div>
        )}
        <BtnInk to={watchTo}>Watch the mend →</BtnInk>
      </div>
    );
  } else if (cooling) {
    body = (
      <div className="cooldown">
        <h3>
          The shop is catching its breath. Next tear in <span className="num">{mmss(cooldownLeft)}</span>.
        </h3>
        <p>Auto-revert keeps the public repo tidy between incidents.</p>
      </div>
    );
  } else {
    const missingNames = missing?.map((m) => MISSING_NAMES[m] ?? m) ?? [];
    body = (
      <>
        <div className="defects" role="radiogroup" aria-label="Pick a defect">
          {DEFECTS.map((d) => (
            <DefectCard
              key={d.key}
              defect={d}
              selected={selected === d.key}
              disabled={tornId !== null || missing !== null}
              onSelect={() => setSelected(d.key)}
            />
          ))}
        </div>
        {missing !== null ? (
          <div className="notconf">
            This deployment isn't wired to {missingNames.length > 0 ? missingNames.join(" or ") : "its live systems"} yet
            — the tear button needs it. The receipts below are from past incidents.
          </div>
        ) : (
          <div className="shiprow">
            {tornId ? (
              progress
            ) : (
              <BtnAmber onClick={() => void onShip()} disabled={!selected || shipping}>
                Ship the bad commit
              </BtnAmber>
            )}
            <div>
              <div className="shipnote">A real commit, on the public repo, through the real CI. Nothing up the sleeve.</div>
              {repoUrl ? (
                <a className="repolink num" href={repoUrl} target="_blank" rel="noreferrer">
                  {bareUrl(repoUrl)} →
                </a>
              ) : null}
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <section className="block" id="tear">
      <h2 className="h2">Tear a hole in it.</h2>
      <p className="blocksub">
        Ship a genuinely bad commit to the live shop — through the real pipeline, onto the public repo. Then watch Darn
        find it, prove it, and mend it.
      </p>
      {body}
    </section>
  );
}

// ------------------------------------------------------------------ (d) the mend, live

function MendSection({
  state,
  liveIncident,
  mendRef,
}: {
  state: AppStateSnapshot | null;
  liveIncident: Incident | null;
  mendRef: RefObject<HTMLElement>;
}) {
  const elapsed = useElapsed(liveIncident?.started_at ?? null);
  const live = liveIncident !== null;

  let states: ThreadState[];
  let labels: ThreadLabel[];
  if (live && liveIncident.stages.length === 6) {
    states = liveIncident.stages.map((s): ThreadState =>
      s.state === "done" ? "done" : s.state === "active" ? "active" : "pending"
    );
    labels = liveIncident.stages.map((s, i) => ({
      name: s.name || STAGE_NAMES[i],
      ts: s.state === "done" ? utcClock(s.done_at) : s.state === "active" ? mmss(elapsed) : null,
    }));
  } else {
    states = STAGE_NAMES.map((): ThreadState => "pending");
    labels = STAGE_NAMES.map((name) => ({ name }));
  }

  const lastMend = state?.last_mend ?? null;
  const thread = (
    <HorizontalThread states={states} tear={live ? 0 : null} labels={labels} className="mend" />
  );

  return (
    <section className="block" ref={mendRef}>
      {!live && (
        <>
          <h2 className="h3">No holes right now. The shop is humming.</h2>
          {lastMend && (
            <p className="lastmend num">
              last mend: {lcFirst(lastMend.title)} · detected → closed in {mmss(lastMend.detected_to_closed_s)}
              {lastMend.pr_number !== null ? ` · PR #${lastMend.pr_number}` : ""}
            </p>
          )}
        </>
      )}
      {live ? (
        <Link to={`/incident/${liveIncident.id}`} className="mendlink" aria-label="Watch the mend">
          {thread}
        </Link>
      ) : (
        thread
      )}
      <p className="byonote">This same view exists for your incidents when you bring your own tenant.</p>
    </section>
  );
}

// ------------------------------------------------------------------ (e) receipts, not promises

interface MendReceipts {
  davis: DavisProblemReceipt | null;
  dql: DqlReceipt | null;
  pr: PrReceipt | null;
}

function MiniPlaceholder({ label }: { label: string }) {
  return (
    <Card className="mini">
      <span className="minilabel">{label}</span>
      <p className="placeholder">appears after the first mend</p>
    </Card>
  );
}

function ReceiptsSection({ lastMendId }: { lastMendId: string | null }) {
  const [receipts, setReceipts] = useState<MendReceipts | null>(null);

  useEffect(() => {
    if (!lastMendId) {
      setReceipts(null);
      return;
    }
    let stale = false;
    api
      .getIncident(lastMendId)
      .then((inc) => {
        if (stale) {
          return;
        }
        const all = inc.stages.flatMap((s) => s.receipts);
        setReceipts({
          davis: (all.find((r) => r.type === "davis_problem") as DavisProblemReceipt | undefined) ?? null,
          dql: (all.find((r) => r.type === "dql") as DqlReceipt | undefined) ?? null,
          pr: (all.find((r) => r.type === "pr") as PrReceipt | undefined) ?? null,
        });
      })
      .catch(() => {
        if (!stale) {
          setReceipts(null);
        }
      });
    return () => {
      stale = true;
    };
  }, [lastMendId]);

  const davis = receipts?.davis ?? null;
  const dql = receipts?.dql ?? null;
  const pr = receipts?.pr ?? null;

  return (
    <section className="block">
      <h2 className="h3">Receipts, not promises.</h2>
      <p className="blocksub">
        Every step the agent takes leaves an artifact a human can independently re-run. Copy any query out of the PR and
        run it in your own Dynatrace — same numbers.
      </p>
      <div className="minis">
        {davis ? (
          <Card className="mini">
            <span className="minilabel">Davis problem</span>
            <div className="titlerow">
              <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
                <rect x="3.1" y="3.1" width="7.8" height="7.8" rx="1.6" transform="rotate(45 7 7)" fill="#E8A33D" />
              </svg>
              {davis.title}
            </div>
            <span className="ml num">{davis.problem_id}</span>
            <span className="ml soft num">
              {davis.entity}
              {davis.started_at ? ` · started ${davis.started_at}` : ""}
            </span>
            {davis.evidence_chips.length > 0 && <span className="chip num">{davis.evidence_chips[0]}</span>}
          </Card>
        ) : (
          <MiniPlaceholder label="Davis problem" />
        )}

        {dql ? (
          <Card className="mini">
            <span className="minilabel">DQL receipt</span>
            <DqlBlock query={dql.query} compact />
          </Card>
        ) : (
          <MiniPlaceholder label="DQL receipt" />
        )}

        {pr ? (
          <Card className="mini">
            <span className="minilabel">PR dossier</span>
            <span className="ml soft num">
              {pr.repo} · {pr.branch}
            </span>
            <div className="titlerow">
              <span>
                {pr.number !== null ? (
                  <>
                    <span className="num">#{pr.number}</span> —{" "}
                  </>
                ) : null}
                {pr.title}
              </span>
            </div>
            {pr.toc.length > 0 && <span className="toc num">{pr.toc.join(" · ")}</span>}
            {pr.checks.length > 0 && (
              <span className="ci num">{pr.checks.map((c) => `${c.name} ${checkMark(c.state)}`).join(" · ")}</span>
            )}
          </Card>
        ) : (
          <MiniPlaceholder label="PR dossier" />
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ (f) medic teaser

function MedicTeaser({ incidentId }: { incidentId: string | null }) {
  return (
    <section className="medic">
      <div>
        <h3>The medic wears a heart monitor.</h3>
        <p>
          Darn's own traces — every tool call, every token — ship to the same Dynatrace tenant that watches the shop.
          Audit the agent like you audit the&nbsp;app.
        </p>
        {incidentId ? (
          <BtnOnInk to={`/incident/${incidentId}?medic=1`}>Watch the medic work</BtnOnInk>
        ) : (
          <BtnOnInk disabled title="appears after the first mend">
            Watch the medic work
          </BtnOnInk>
        )}
      </div>
      <svg viewBox="0 0 360 130" fill="none" aria-hidden="true">
        <path
          d="M4 72h54l9-13 9 13h40l10-42 13 72 10-48 7 18h86l10-15 10 15h94"
          stroke="#E8A33D"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="12 6"
        />
      </svg>
    </section>
  );
}

// ------------------------------------------------------------------ (g) mended strip

function MendedStrip({ refreshKey }: { refreshKey: string | null }) {
  const [mended, setMended] = useState<IncidentSummary[]>([]);

  useEffect(() => {
    let stale = false;
    api
      .listIncidents()
      .then((res) => {
        if (!stale) {
          setMended(res.incidents.filter((i) => i.status === "verified_closed"));
        }
      })
      .catch(() => {
        if (!stale) {
          setMended([]);
        }
      });
    return () => {
      stale = true;
    };
  }, [refreshKey]);

  if (mended.length === 0) {
    return null;
  }
  return (
    <section className="block">
      <h2 className="h3">Mended</h2>
      <div className="mrow">
        {mended.map((m) => (
          <Card key={m.id} className="mcard">
            <div className="mn">{m.title}</div>
            <div className="mt num">detected → closed {mmss(m.detected_to_closed_s)}</div>
            <div className="mlinks">
              {m.pr_number !== null ? (
                <a className="pr num" href={prUrl(m.repo, m.pr_number)} target="_blank" rel="noreferrer">
                  PR #{m.pr_number}
                </a>
              ) : (
                <span />
              )}
              <Link className="rc" to={`/incident/${m.id}`}>
                receipts →
              </Link>
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ page

export default function ShopFloor() {
  const { state, liveIncident, reload } = useAppState();
  const mendRef = useRef<HTMLElement>(null);
  const location = useLocation();

  // honor /#wont-do (footer link) and /#tear deep links
  useEffect(() => {
    if (location.hash) {
      document.getElementById(location.hash.slice(1))?.scrollIntoView();
    }
  }, [location.hash]);

  const onTearCta = (e: MouseEvent<HTMLElement>) => {
    e.preventDefault();
    document.getElementById("tear")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const live = liveIncident && liveIncident.status === "live" ? liveIncident : null;
  const lastMendId = state?.last_mend?.id ?? null;
  const medicTarget = live?.id ?? lastMendId;

  return (
    <div className="page sf">
      <div className="blob amber" aria-hidden="true" />
      <div className="blob cream" aria-hidden="true" />

      <div className="wrap">
        {/* (a) hero + (b) live health card */}
        <section className="hero">
          <div>
            <Wordmark size={84} />
            <h1 className="display">Production broke? Darn&nbsp;it.</h1>
            <p className="herosub">
              When a deploy tears a hole in production, Darn finds the exact commit, writes the fix, and opens a pull
              request where every claim is a receipt you can re-run in Dynatrace.
            </p>
            <div className="ctas">
              <BtnAmber href="#tear" onClick={onTearCta}>
                Tear a hole in it
              </BtnAmber>
              <BtnGhost to="/yours">Use it on yours</BtnGhost>
            </div>
            <p className="micro">Fixes with receipts.</p>
          </div>
          <HealthCardView health={state?.health ?? null} tenantUrl={state?.tenant_url ?? ""} />
        </section>

        {/* (c) tear a hole in it */}
        <TearSection state={state} liveIncident={live} reload={reload} mendRef={mendRef} />

        {/* (d) the mend, live */}
        <MendSection state={state} liveIncident={live} mendRef={mendRef} />

        {/* (e) receipts, not promises */}
        <ReceiptsSection lastMendId={lastMendId} />

        {/* (f) the medic teaser */}
        <MedicTeaser incidentId={medicTarget} />

        {/* (g) mended */}
        <MendedStrip refreshKey={lastMendId} />

        {/* (h) what darn won't do */}
        <section className="block" id="wont-do">
          <h2 className="h3">What Darn won't do</h2>
          <div className="wontcard">
            <ul>
              <li>
                <b>Pure infra outages.</b> If the cause isn't in the code, Darn says so — with evidence — and stops.
              </li>
              <li>
                <b>Fixes without receipts.</b> If it can't prove it, it doesn't propose it.
              </li>
              <li>
                <b>Merging.</b> A human approves every fix. Always.
              </li>
            </ul>
            <div className="wontfoot">Scope honesty is a feature.</div>
          </div>
        </section>
      </div>

      {/* (i) use it on yours band */}
      <section className="byo">
        <h3>The demo is the toy. This is the tool.</h3>
        <p>
          Connect your tenant, install the GitHub App, map a service. Darn watches your Davis problems and opens PRs
          with the same receipts.
        </p>
        <BtnInk to="/yours">Connect your tenant</BtnInk>
      </section>
    </div>
  );
}
