/**
 * Stage-level layouts for the incident ledger: the collapsed
 * 56px summary line per stage, and the expanded body per stage key —
 * including the tied-off knot card and the stage-5 oversight beat.
 */

import { Fragment, type ReactNode } from "react";
import type { Incident, PresenceInfo, Stage } from "../../lib/api";
import { mmss, money, shortSha, utcClock } from "../../lib/format";
import { useElapsed } from "../../lib/store";
import { BtnAmber, BtnGhost, BtnInk } from "../Buttons";
import { PillOk } from "../Pills";
import {
  ReceiptListFooter,
  ReceiptStream,
  WallClockCard,
  diffStats,
  findIncidentReceipt,
  findReceipt,
  wrapNums,
} from "./receipts";

// ------------------------------------------------------------------ actions

export interface StageActions {
  onApprove: () => void;
  onDeclineAsk: () => void;
  onPickup: () => void;
  busy: boolean;
  actionError: string | null;
}

// ------------------------------------------------------------------ summary line (collapsed 56px row)

function joinSep(parts: ReactNode[]): ReactNode {
  return parts.map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <span className="sep">·</span>}
      {part}
    </Fragment>
  ));
}

function firstCheckText(incident: Incident): string | null {
  const pr = findIncidentReceipt(incident, "pr");
  const check = pr?.checks[0];
  if (!check) {
    return null;
  }
  const s = check.state.toLowerCase();
  const mark = ["success", "ok", "passed", "done"].includes(s)
    ? "✓"
    : ["failure", "failed", "error"].includes(s)
      ? "✕"
      : `— ${s === "queued" ? "queued" : "running"}`;
  return `${check.name} ${mark}`;
}

/** The key-receipt summary shown in the stage header (`.skey`). */
export function stageSummary(
  stage: Stage,
  incident: Incident,
  presence: PresenceInfo | null
): ReactNode {
  const parts: string[] = [];
  switch (stage.key) {
    case "detected": {
      const davis = findReceipt(stage.receipts, "davis_problem");
      if (davis) {
        parts.push(`Davis problem ${davis.problem_id}`);
        if (davis.evidence_chips[0]) {
          parts.push(davis.evidence_chips[0]);
        }
      } else if (stage.state === "active") {
        parts.push("waiting on Davis — real signal takes minutes");
      }
      break;
    }
    case "diagnosed": {
      if (stage.state === "tied_off") {
        const knot = findReceipt(stage.receipts, "knot");
        if (knot?.label) {
          parts.push(knot.label);
        } else {
          parts.push("not a code problem");
        }
        break;
      }
      const ruler = findReceipt(stage.receipts, "timing_ruler");
      if (ruler) {
        parts.push(`suspect ${shortSha(ruler.deploy_sha)}`);
      }
      const note = findReceipt(stage.receipts, "note");
      const n = note?.text.match(/\d+/)?.[0];
      if (n) {
        parts.push(`DQL ×${n}`);
      }
      parts.push("Grail forensics");
      break;
    }
    case "fix_written": {
      const meta = findReceipt(stage.receipts, "model_meta");
      const diff = findReceipt(stage.receipts, "proposed_diff");
      if (meta) {
        parts.push(meta.model);
      }
      if (diff) {
        const { adds, rems } = diffStats(diff.diff);
        parts.push(`diff +${adds} −${rems}`);
      }
      if (meta?.cost_usd !== null && meta?.cost_usd !== undefined) {
        parts.push(`cost ${money(meta.cost_usd)}`);
      }
      break;
    }
    case "pr_open": {
      const pr = findReceipt(stage.receipts, "pr");
      if (pr) {
        if (pr.number !== null) {
          parts.push(`#${pr.number}`);
        }
        parts.push(pr.repo);
        const check = firstCheckText(incident);
        if (check) {
          parts.push(check);
        }
      }
      break;
    }
    case "approved": {
      const approval = findReceipt(stage.receipts, "approval");
      if (approval) {
        parts.push(`by ${approval.by}`);
        parts.push(utcClock(approval.at));
      } else if (stage.state === "active") {
        parts.push(presence?.holder ? "waiting on you" : "waiting on the needle-holder");
        const pr = findIncidentReceipt(incident, "pr");
        if (pr?.number !== null && pr?.number !== undefined) {
          parts.push(`PR #${pr.number}`);
        }
        const check = firstCheckText(incident);
        if (check) {
          parts.push(check);
        }
      }
      break;
    }
    case "verified": {
      const closure = findReceipt(stage.receipts, "closure");
      const replay = findReceipt(stage.receipts, "replay");
      if (closure?.closed_at) {
        parts.push(`Davis closed ${closure.closed_at}`);
      }
      if (replay && replay.before_status !== null && replay.after_status !== null) {
        parts.push(`replay ${replay.before_status} → ${replay.after_status}`);
      }
      break;
    }
  }
  return joinSep(parts.map((p) => wrapNums(p)));
}

/** "+mm:ss" elapsed-from-incident-start; ticks while the stage is active. */
export function StageElapsed({ stage, incident }: { stage: Stage; incident: Incident }) {
  const ticking = useElapsed(stage.state === "active" ? incident.started_at : null);
  let value: number | null = null;
  if (stage.done_at !== null) {
    value = stage.done_at - incident.started_at;
  } else if (stage.state === "active") {
    value = ticking;
  }
  return (
    <span className="selapsed num">{value !== null ? `+${mmss(value)}` : "—"}</span>
  );
}

// ------------------------------------------------------------------ waiting lines

const DETECT_WAIT_LINES = [
  "traffic is hitting the broken endpoint…",
  "Davis needs a few minutes of signal…",
];

function DetectionWait({ since }: { since: number | null }) {
  const elapsed = useElapsed(since);
  const line = DETECT_WAIT_LINES[Math.floor((elapsed ?? 0) / 6) % DETECT_WAIT_LINES.length];
  return (
    <div className="waiting">
      <span key={line}>{line}</span>
      <span className="num">{mmss(elapsed)}</span>
    </div>
  );
}

function WorkingLine() {
  return <p className="cap">receipts appear as they&rsquo;re emitted…</p>;
}

// ------------------------------------------------------------------ per-stage expanded bodies

function DetectedBody({ stage, incident }: { stage: Stage; incident: Incident }) {
  if (stage.state === "active" && stage.receipts.length === 0) {
    return <DetectionWait since={stage.started_at ?? incident.started_at} />;
  }
  const davis = findReceipt(stage.receipts, "davis_problem");
  const link = davis?.dynatrace_link ?? incident.problem_url;
  return (
    <>
      <p className="lead">Raised by Davis before Darn moved a muscle.</p>
      <ReceiptStream stage={stage} incident={incident} />
      <div className="receiptrow">
        {link && (
          <a className="go" href={link} target="_blank" rel="noreferrer">
            Open problem in Dynatrace →
          </a>
        )}
        <span className="cap">Receipt: the problem ID. Don&rsquo;t take Darn&rsquo;s word for it.</span>
      </div>
    </>
  );
}

function DiagnosedBody({ stage, incident }: { stage: Stage; incident: Incident }) {
  if (stage.state === "tied_off") {
    return (
      <>
        <div className="khead">
          <span className="t">This hole isn&rsquo;t in the code.</span>
          <PillOk>Tied off — not a code problem</PillOk>
        </div>
        <div style={{ marginTop: 18 }}>
          <ReceiptStream stage={stage} incident={incident} />
        </div>
      </>
    );
  }
  if (stage.state === "active" && stage.receipts.length === 0) {
    return <WorkingLine />;
  }
  const note = findReceipt(stage.receipts, "note");
  const dqlCount = note?.text.match(/\d+/)?.[0] ?? null;
  return (
    <>
      <ReceiptStream stage={stage} incident={incident} skip={["note"]} />
      {note && (
        <div className="sfoot">
          <span className="cap" style={{ fontSize: 13.5, color: "var(--ink)" }}>
            Every block above is copy-pasteable into your tenant. Same query, same numbers.
          </span>
          <span className="spring" />
          <span className="counter">
            DQL queries this diagnosis: <span className="num">{dqlCount ?? "—"}</span>
          </span>
        </div>
      )}
    </>
  );
}

function FixWrittenBody({ stage, incident }: { stage: Stage; incident: Incident }) {
  if (stage.state === "active" && stage.receipts.length === 0) {
    return <WorkingLine />;
  }
  return (
    <>
      <p className="lead">Written by Gemini on Vertex AI, briefed with the receipts above.</p>
      <ReceiptStream stage={stage} incident={incident} />
    </>
  );
}

function VerifiedBody({ stage, incident }: { stage: Stage; incident: Incident }) {
  if (stage.state === "active" && stage.receipts.length === 0) {
    return <WorkingLine />;
  }
  const closure = findReceipt(stage.receipts, "closure");
  return (
    <>
      <p className="lead">&ldquo;Fixed&rdquo; is not the agent&rsquo;s opinion.</p>
      <ReceiptStream stage={stage} incident={incident} />
      {closure && <ReceiptListFooter receipt={closure} incident={incident} />}
      <WallClockCard incident={incident} />
    </>
  );
}

/** Expanded stage body (inside `.sbody`). Stage-5-active renders elsewhere. */
export function StageBody({ stage, incident }: { stage: Stage; incident: Incident }) {
  switch (stage.key) {
    case "detected":
      return <DetectedBody stage={stage} incident={incident} />;
    case "diagnosed":
      return <DiagnosedBody stage={stage} incident={incident} />;
    case "fix_written":
      return <FixWrittenBody stage={stage} incident={incident} />;
    case "verified":
      return <VerifiedBody stage={stage} incident={incident} />;
    default:
      if (stage.state === "active" && stage.receipts.length === 0) {
        return <WorkingLine />;
      }
      return <ReceiptStream stage={stage} incident={incident} />;
  }
}

// ------------------------------------------------------------------ stage 5 — the oversight beat

/** The needle-holder's approve/decline panel (replaces `.sbody`). */
export function ApprovePanel({
  incident,
  actions,
}: {
  incident: Incident;
  actions: StageActions;
}) {
  return (
    <div className="approve">
      {incident.kind === "byo" && (
        <p className="cap15" style={{ margin: "0 0 16px" }}>
          Approval happens on your PR, on GitHub, by someone with merge rights. Darn waits.
        </p>
      )}
      <div className="btns">
        <BtnInk size="big" onClick={actions.onApprove} disabled={actions.busy}>
          Approve fix
        </BtnInk>
        <BtnGhost onClick={actions.onDeclineAsk} disabled={actions.busy}>
          Decline &amp; revert
        </BtnGhost>
      </div>
      <p className="cap15">Darn never merges by itself. You hold the needle.</p>
      {actions.actionError && (
        <p className="cap" style={{ marginTop: 12 }}>
          {actions.actionError}
        </p>
      )}
    </div>
  );
}

/** Spectator / pickup / BYO-waiting card — a bare card, no stage header. */
export function SpectatorCard({
  incident,
  presence,
  actions,
}: {
  incident: Incident;
  presence: PresenceInfo | null;
  actions: StageActions;
}) {
  if (incident.kind === "byo") {
    return (
      <div className="scard spect">
        <span className="t">
          Approval happens on your PR, on GitHub, by someone with merge rights. Darn waits.
        </span>
      </div>
    );
  }
  if (presence?.can_pickup) {
    return (
      <div className="scard spect">
        <span className="presence faint" />
        <BtnAmber onClick={actions.onPickup} disabled={actions.busy}>
          Pick up the needle
        </BtnAmber>
        {actions.actionError && <span className="cap">{actions.actionError}</span>}
      </div>
    );
  }
  return (
    <div className="scard spect">
      <span className="presence" />
      <span className="t">{presence?.holder_label || "Someone"} holds the needle.</span>
    </div>
  );
}
