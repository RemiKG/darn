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
