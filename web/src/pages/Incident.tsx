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
