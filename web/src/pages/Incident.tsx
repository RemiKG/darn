/**
 * Incident view — `/incident/:id`, the receipt ledger. Works identically
 * for demo and BYO incidents; completed incidents stay at stable URLs
 * forever — they ARE the archive.
 *
 * - Header band: breadcrumb, title + status pill, live-ticking meta row,
 *   the medic's-heartbeat button (drawer) and the Dynatrace deep link.
 * - The vertical thread spine: solid done / amber-dash active / faint
 *   pending / knot when tied off. The active stage auto-expands (and follows
 *   SSE updates); done stages collapse to 56px summary rows that toggle.
 * - Stage 5 is the single human action in the loop: approve / decline
 *   (in-app confirm, never window.confirm) / pick up the needle.
 * Everything renders from live incident data — never hardcoded numbers.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Incident as IncidentModel, type PresenceInfo, type Stage } from "../lib/api";
import { mmss, utcClock } from "../lib/format";
import { useElapsed, useIncident } from "../lib/store";
import { cx } from "../lib/cx";
import { BtnGhost, BtnInk } from "../components/Buttons";
import { PillAmber, PillNeutral, PillOk } from "../components/Pills";
import { VerticalSpine } from "../components/Thread";
import EmptyState from "../components/EmptyState";
import HeartbeatDrawer from "../components/HeartbeatDrawer";
import {
  ApprovePanel,
  SpectatorCard,
  StageBody,
  StageElapsed,
  stageSummary,
  type StageActions,
} from "../components/incident/StageBody";
import "../styles/pages/incident.css";

// ------------------------------------------------------------------ status pill

function StatusPill({ incident }: { incident: IncidentModel }) {
  switch (incident.status) {
    case "live":
      return (
        <PillAmber>
          Mending — stage <span className="num">{incident.stage_index + 1}</span> of{" "}
          <span className="num">6</span>
        </PillAmber>
      );
    case "verified_closed":
      return <PillOk>Verified closed</PillOk>;
    case "tied_off":
      return <PillNeutral>Tied off — not a code problem</PillNeutral>;
    case "declined_reverted":
      return <PillNeutral>Declined — reverted</PillNeutral>;
    case "declined_timeout":
      return <PillNeutral>Declined — reverted (timeout)</PillNeutral>;
  }
}

// ------------------------------------------------------------------ decline confirm (in-app dialog)

function DeclineDialog({
  busy,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="dc-backdrop" onClick={onCancel}>
      <div
        className="dc-card"
        role="dialog"
        aria-modal="true"
        aria-label="Decline and revert"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="t">Close the PR and revert the bad commit? The receipts stay.</p>
        <div className="btns">
          <BtnGhost onClick={onCancel} disabled={busy}>
            Cancel
          </BtnGhost>
          <BtnInk onClick={onConfirm} disabled={busy}>
            Decline &amp; revert
          </BtnInk>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ one stage row on the thread

interface StageRowProps {
  stage: Stage;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  knot: boolean;
  incident: IncidentModel;
  presence: PresenceInfo | null;
  expanded: boolean;
  onToggle: () => void;
  actions: StageActions;
}

function StageRow({
  stage,
  index,
  isFirst,
  isLast,
  knot,
  incident,
  presence,
  expanded,
  onToggle,
  actions,
}: StageRowProps) {
  const spineState =
    stage.state === "active" ? "active" : stage.state === "pending" ? "pending" : "done";

  // stage 5 while the decision is live
  const oversight = stage.key === "approved" && stage.state === "active";
  const holder = presence?.holder ?? false;

  if (oversight && !holder) {
    // spectator / pick-up / BYO-waiting: a bare card hung on the thread
    const nodeTop = presence?.can_pickup ? 44 : 31;
    return (
      <section className="stage">
        <VerticalSpine state="active" first={isFirst} last={isLast} nodeTop={nodeTop} />
        <div className="body">
          <SpectatorCard incident={incident} presence={presence} actions={actions} />
        </div>
      </section>
    );
  }

  const canToggle = stage.state !== "pending";
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (canToggle && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onToggle();
    }
  };

  return (
    <section className={cx("stage", stage.state === "pending" && "pending")}>
      <VerticalSpine state={spineState} first={isFirst} last={isLast && !knot} knot={knot} />
      <div className="body">
        <div className={cx("scard", !expanded && "collapsed", knot && "knotcard")}>
          <div
            className={cx("shead", canToggle && "clickable")}
            role={canToggle ? "button" : undefined}
            tabIndex={canToggle ? 0 : undefined}
            aria-expanded={canToggle ? expanded : undefined}
            onClick={canToggle ? onToggle : undefined}
            onKeyDown={onKeyDown}
          >
            <span className="sidx num">{String(index + 1).padStart(2, "0")}</span>
            <span className="sname">{stage.name}</span>
            <span className="skey">{stageSummary(stage, incident, presence)}</span>
            <StageElapsed stage={stage} incident={incident} />
          </div>
          {expanded &&
            (oversight && holder ? (
              <ApprovePanel incident={incident} actions={actions} />
            ) : (
              <div className="sbody">
                <StageBody stage={stage} incident={incident} />
              </div>
            ))}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ the page

export default function Incident() {
  const { id } = useParams<{ id: string }>();
  const { incident, presence, medic, error, reload } = useIncident(id);
  const [searchParams] = useSearchParams();
  const [drawerOpen, setDrawerOpen] = useState(() => searchParams.get("medic") === "1");
  const [declineOpen, setDeclineOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // expand/collapse: user choices override the defaults; the auto-expand
  // follows the active stage as SSE updates arrive.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const activeKey = incident?.stages.find((s) => s.state === "active")?.key ?? null;
  const prevActiveRef = useRef<string | null>(null);
  useEffect(() => {
    if (activeKey && activeKey !== prevActiveRef.current) {
      prevActiveRef.current = activeKey;
      setOverrides((prev) => {
        if (!(activeKey in prev)) {
          return prev;
        }
        const next = { ...prev };
        delete next[activeKey];
        return next;
      });
    }
  }, [activeKey]);

  const liveWall = useElapsed(incident && incident.status === "live" ? incident.started_at : null);

  const act = useCallback(
    (call: () => Promise<unknown>, after?: () => void) => {
      setBusy(true);
      setActionError(null);
      call()
        .then(() => {
          after?.();
          reload();
        })
        .catch(() => {
          setActionError("That didn’t go through — the server said no. Try again.");
        })
        .finally(() => setBusy(false));
    },
    [reload]
  );

  if (error) {
    const is404 = error.includes("404");
    return (
      <main className="wrap incident-page">
        {is404 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "64px 0 24px" }}>
            <EmptyState size={320}>This incident never existed.</EmptyState>
            <BtnInk to="/">Back to the shop floor</BtnInk>
            <span className="num" style={{ fontSize: 12, color: "var(--ink-faint)", marginTop: 18 }}>
              404
            </span>
          </div>
        ) : (
          <div className="retryrow">
            <span>The thread slipped — this incident wouldn&rsquo;t load.</span>
            <BtnGhost size="sm" onClick={reload}>
              Try again
            </BtnGhost>
          </div>
        )}
      </main>
    );
  }

  if (!incident) {
    return <main className="wrap incident-page" style={{ minHeight: 480 }} />;
  }

  const actions: StageActions = {
    onApprove: () => act(() => api.approve(incident.id)),
    onDeclineAsk: () => setDeclineOpen(true),
    onPickup: () => act(() => api.pickup(incident.id)),
    busy,
    actionError,
  };

  const wall =
    incident.status === "live"
      ? liveWall
      : incident.ended_at !== null
        ? incident.ended_at - incident.started_at
        : null;
  const watching = presence?.watching ?? incident.watching;

  // tied-off / declined incidents end at the knot: later stages never render
  const terminal =
    incident.status === "tied_off" ||
    incident.status === "declined_reverted" ||
    incident.status === "declined_timeout";
  const stages = incident.stages.filter(
    (s) => s.state !== "skipped" && !(terminal && s.state === "pending")
  );

  const defaultExpanded = (stage: Stage): boolean =>
    incident.status === "live"
      ? stage.state === "active" || stage.state === "tied_off"
      : stage.state !== "pending";
  const isExpanded = (stage: Stage): boolean => overrides[stage.key] ?? defaultExpanded(stage);
  const toggle = (stage: Stage) =>
    setOverrides((prev) => ({ ...prev, [stage.key]: !isExpanded(stage) }));

  return (
    <main className="wrap incident-page">
      {/* ===== header band ===== */}
      <div className="hband">
        <div className="crumb">
          <Link to="/">shop floor</Link> / incident{" "}
          <span className="num">{incident.problem_id ?? incident.id}</span>
        </div>
        <div className="h1row">
          <h1>{incident.title}</h1>
          <StatusPill incident={incident} />
        </div>
        <div className="metarow">
          <span className="meta">
            started <span className="num">{utcClock(incident.started_at)}</span> UTC{" "}
            <span className="sep">·</span> wall clock <span className="num">{mmss(wall)}</span>{" "}
            <span className="sep">·</span> <span className="num">{watching}</span> watching
          </span>
          <span className="spring" />
          <BtnGhost size="sm" onClick={() => setDrawerOpen(true)}>
            The medic&rsquo;s heartbeat
          </BtnGhost>
          {incident.problem_url && (
            <a className="go" href={incident.problem_url} target="_blank" rel="noreferrer">
              Open problem in Dynatrace →
            </a>
          )}
        </div>
      </div>

      {/* ===== the receipt ledger ===== */}
      <div className="ledger">
        {stages.map((stage, i) => (
          <StageRow
            key={stage.key}
            stage={stage}
            index={incident.stages.indexOf(stage)}
            isFirst={i === 0}
            isLast={i === stages.length - 1}
            knot={terminal && i === stages.length - 1}
            incident={incident}
            presence={presence}
            expanded={isExpanded(stage)}
            onToggle={() => toggle(stage)}
            actions={actions}
          />
        ))}
      </div>

      {drawerOpen && (
        <HeartbeatDrawer
          incidentId={incident.id}
          medic={medic}
          onClose={() => setDrawerOpen(false)}
        />
      )}

      {declineOpen && (
        <DeclineDialog
          busy={busy}
          onCancel={() => setDeclineOpen(false)}
          onConfirm={() => act(() => api.decline(incident.id), () => setDeclineOpen(false))}
        />
      )}
    </main>
  );
}
