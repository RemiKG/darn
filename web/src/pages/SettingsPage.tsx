/**
 * Power user settings — /yours/settings. Two columns: sticky anchor nav
 * left (active section tracks scroll), content right. Every row: label +
 * one-line caption + control. Changed-but-unsaved rows get the subtle
 * amber thread underline; a sticky save bar slides in while dirty.
 * Locked toggles are server-enforced constants — disabled, no change events.
 *
 * Data: GET /api/settings on load, PUT /api/settings on save (locked fields
 * always sent as their constants). The two Data & privacy delete actions have
 * no dedicated endpoint — they POST /api/settings/delete-* and
 * show a calm honest failure line if the deployment doesn't answer.
 */

import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { api, type DarnSettings } from "../lib/api";
import { groupedInt } from "../lib/format";
import Card from "../components/Card";
import { BtnGhost, BtnInk } from "../components/Buttons";
import { ChipsInput, Field, Radios, SelectBox, Switch } from "../components/settings/controls";
import ConfirmModal from "../components/settings/ConfirmModal";
import "../styles/pages/settings.css";

// ------------------------------------------------------------------ sections

const SECTIONS = [
  { id: "detection", label: "Detection", kn: "01" },
  { id: "diagnosis", label: "Diagnosis", kn: "02" },
  { id: "fix-policy", label: "Fix policy", kn: "03" },
  { id: "oversight", label: "Oversight", kn: "04" },
  { id: "budgets", label: "Budgets", kn: "05" },
  { id: "data-privacy", label: "Data & privacy", kn: "06" },
  { id: "the-medic", label: "The medic", kn: "07" },
] as const;

const TIMEZONES = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
];

const RETENTION_OPTIONS = [
  { value: "forever", label: "keep incidents forever" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "365d", label: "365 days" },
];

// ------------------------------------------------------------------ form model
// Text inputs hold strings while editing; (de)serialization happens at the
// load/save seam so dirty-checking can compare normalized values.

type Retention = DarnSettings["data"]["retention"];
type ProblemScope = DarnSettings["detection"]["problem_scope"];

interface FormState {
  poll: string;
  scope: ProblemScope;
  quietOn: boolean;
  quietStart: string;
  quietEnd: string;
  quietTz: string;
  dqlBudget: string;
  lookback: string;
  branchPrefix: string;
  labels: string[];
  draftPrs: boolean;
  maxFiles: string;
  maxLines: string;
  denylist: string;
  declineTidy: boolean;
  webhook: string;
  tokenBudget: string;
  spendCap: string;
  dqlDay: string;
  retention: Retention;
  shareTimings: boolean;
}

/** Every editable row, in page order (locked rows can never be dirty). */
type RowKey =
  | "poll"
  | "scope"
  | "quiet"
  | "dqlBudget"
  | "lookback"
  | "branchPrefix"
  | "labels"
  | "draftPrs"
  | "maxSize"
  | "denylist"
  | "declineTidy"
  | "webhook"
  | "tokenBudget"
  | "spendCap"
  | "dqlDay"
  | "retention"
  | "shareTimings";

function fromSettings(s: DarnSettings): FormState {
  return {
    poll: String(s.detection.poll_seconds),
    scope: s.detection.problem_scope,
    quietOn: s.detection.quiet_hours.enabled,
    quietStart: s.detection.quiet_hours.start,
    quietEnd: s.detection.quiet_hours.end,
    quietTz: s.detection.quiet_hours.timezone,
    dqlBudget: String(s.diagnosis.dql_budget_per_incident),
    lookback: String(s.diagnosis.lookback_minutes),
    branchPrefix: s.fix_policy.branch_prefix,
    labels: [...s.fix_policy.pr_labels],
    draftPrs: s.fix_policy.draft_prs,
    maxFiles: String(s.fix_policy.max_changed_files),
    maxLines: String(s.fix_policy.max_diff_lines),
    denylist: s.fix_policy.path_denylist.join("\n"),
    declineTidy: s.oversight.decline_tidy,
    webhook: s.oversight.webhook_url,
    tokenBudget: groupedInt(s.budgets.token_budget_per_fix),
    spendCap: s.budgets.monthly_spend_cap_usd.toFixed(2),
    dqlDay: String(s.budgets.dql_budget_per_day),
    retention: s.data.retention,
    shareTimings: s.medic.share_timings_with_demo,
  };
}

/** "40 000" → 40000; null when not a whole number. */
function parseWhole(v: string): number | null {
  const t = v.replace(/[\s ]/g, "");
  return /^\d+$/.test(t) ? Number(t) : null;
}

/** "25.00" → 25; null when not dollars(.cents). */
function parseMoney(v: string): number | null {
  const t = v.trim();
  return /^\d+(\.\d{1,2})?$/.test(t) ? Number(t) : null;
}

function splitDenylist(v: string): string[] {
  return v
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Normalized per-row values — a row is dirty when these differ. */
function canon(f: FormState): Record<RowKey, string> {
  return {
    poll: String(parseWhole(f.poll)),
    scope: f.scope,
    quiet: [f.quietOn, f.quietStart, f.quietEnd, f.quietTz].join("|"),
    dqlBudget: String(parseWhole(f.dqlBudget)),
    lookback: String(parseWhole(f.lookback)),
    branchPrefix: f.branchPrefix,
    labels: f.labels.join(" "),
    draftPrs: String(f.draftPrs),
    maxSize: `${parseWhole(f.maxFiles)}|${parseWhole(f.maxLines)}`,
    denylist: splitDenylist(f.denylist).join(" "),
    declineTidy: String(f.declineTidy),
    webhook: f.webhook.trim(),
    tokenBudget: String(parseWhole(f.tokenBudget)),
    spendCap: String(parseMoney(f.spendCap)),
    dqlDay: String(parseWhole(f.dqlDay)),
    retention: f.retention,
    shareTimings: String(f.shareTimings),
  };
}

/** Calm inline messages, mirroring the contract ranges (10–300 s etc.). */
function validate(f: FormState): Partial<Record<RowKey, string>> {
  const errs: Partial<Record<RowKey, string>> = {};
  const poll = parseWhole(f.poll);
  if (poll === null || poll < 10 || poll > 300) {
    errs.poll = "keep it between 10 and 300";
  }
  if (f.quietOn && (!TIME_RE.test(f.quietStart) || !TIME_RE.test(f.quietEnd))) {
    errs.quiet = "use 24-hour HH:MM";
  }
  const dql = parseWhole(f.dqlBudget);
  if (dql === null || dql < 1) {
    errs.dqlBudget = "a whole number, 1 or more";
  }
  const look = parseWhole(f.lookback);
  if (look === null || look < 1) {
    errs.lookback = "a whole number of minutes, 1 or more";
  }
  if (f.branchPrefix.trim() === "") {
    errs.branchPrefix = "can’t be empty";
  } else if (/\s/.test(f.branchPrefix)) {
    errs.branchPrefix = "no spaces in a branch prefix";
  }
  const files = parseWhole(f.maxFiles);
  const lines = parseWhole(f.maxLines);
  if (files === null || files < 1 || lines === null || lines < 1) {
    errs.maxSize = "whole numbers, 1 or more";
  }
  if (f.webhook.trim() !== "" && !/^https?:\/\/.+/.test(f.webhook.trim())) {
    errs.webhook = "starts with http:// or https://";
  }
  const tokens = parseWhole(f.tokenBudget);
  if (tokens === null || tokens < 1) {
    errs.tokenBudget = "a whole number of tokens, 1 or more";
  }
  if (parseMoney(f.spendCap) === null) {
    errs.spendCap = "dollars and cents, like 25.00";
  }
  const day = parseWhole(f.dqlDay);
  if (day === null || day < 1) {
    errs.dqlDay = "a whole number, 1 or more";
  }
  return errs;
}

/** Build the PUT body; locked fields are always their server-enforced constants. */
function toSettings(f: FormState): DarnSettings {
  return {
    detection: {
      poll_seconds: parseWhole(f.poll) ?? 30,
      problem_scope: f.scope,
      quiet_hours: { enabled: f.quietOn, start: f.quietStart, end: f.quietEnd, timezone: f.quietTz },
    },
    diagnosis: {
      dql_budget_per_incident: parseWhole(f.dqlBudget) ?? 12,
      lookback_minutes: parseWhole(f.lookback) ?? 30,
      stop_when_not_code: true,
    },
    fix_policy: {
      branch_prefix: f.branchPrefix,
      pr_labels: f.labels,
      draft_prs: f.draftPrs,
      max_changed_files: parseWhole(f.maxFiles) ?? 5,
      max_diff_lines: parseWhole(f.maxLines) ?? 120,
      path_denylist: splitDenylist(f.denylist),
      one_open_pr_per_service: true,
    },
    oversight: {
      darn_can_merge: false,
      decline_tidy: f.declineTidy,
      webhook_url: f.webhook.trim(),
    },
    budgets: {
      token_budget_per_fix: parseWhole(f.tokenBudget) ?? 40000,
      monthly_spend_cap_usd: parseMoney(f.spendCap) ?? 25,
      dql_budget_per_day: parseWhole(f.dqlDay) ?? 200,
    },
    data: { retention: f.retention },
    medic: { self_traces: true, share_timings_with_demo: f.shareTimings },
  };
}

/** No contract endpoint exists for the delete actions — best-effort POST. */
async function postDelete(path: string): Promise<void> {
  const res = await fetch(path, { method: "POST", credentials: "include" });
  if (!res.ok) {
    throw new Error(`delete failed: ${res.status}`);
  }
}

// ------------------------------------------------------------------ row shell

interface RowProps {
  label: ReactNode;
  caption?: ReactNode;
  /** Align controls to the top (.row.top). */
  top?: boolean;
  dirty?: boolean;
  /** The "What Darn stores" row lets the left column run full width. */
  wideLeft?: boolean;
  leftExtra?: ReactNode;
  children?: ReactNode;
}

function Row({ label, caption, top, dirty, wideLeft, leftExtra, children }: RowProps) {
  const cls = ["row", top ? "top" : "", dirty ? "unsaved" : ""].filter(Boolean).join(" ");
  return (
    <div className={cls}>
      <div className="left" style={wideLeft ? { maxWidth: "none" } : undefined}>
        <div className="lab">{label}</div>
        {caption ? <div className="cap">{caption}</div> : null}
        {leftExtra}
      </div>
      {children}
    </div>
  );
}

function Kick({ kn, children }: { kn: string; children: ReactNode }) {
  return (
    <div className="kick">
      <span className="kn">{kn}</span> {children}
    </div>
  );
}

// ------------------------------------------------------------------ page

export default function SettingsPage() {
  const [saved, setSaved] = useState<DarnSettings | null>(null);
  const [draft, setDraft] = useState<FormState | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [tenantHost, setTenantHost] = useState("");
  const [modal, setModal] = useState<null | "incidents" | "tokens">(null);
  const [current, setCurrent] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    let stale = false;
    api
      .getSettings()
      .then((s) => {
        if (!stale) {
          setSaved(s);
          setDraft(fromSettings(s));
        }
      })
      .catch(() => {
        if (!stale) {
          setLoadFailed(true);
        }
      });
    // the typed-confirm word is the tenant host when one is connected
    api
      .getYours()
      .then((y) => {
        if (!stale && y.connected && y.tenant_host) {
          setTenantHost(y.tenant_host);
        }
      })
      .catch(() => {
        /* fall back to typing "delete" */
      });
    return () => {
      stale = true;
    };
  }, []);

  // active anchor tracks scroll (the last section whose top passed the fold)
  const loaded = draft !== null;
  useEffect(() => {
    const onScroll = () => {
      let cur: string = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= 140) {
          cur = s.id;
        }
      }
      setCurrent(cur);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [loaded]);

  const base = useMemo(() => (saved ? canon(fromSettings(saved)) : null), [saved]);
  const cur = useMemo(() => (draft ? canon(draft) : null), [draft]);
  const errs = useMemo(() => (draft ? validate(draft) : {}), [draft]);

  const dirty: Partial<Record<RowKey, boolean>> = {};
  if (base && cur) {
    for (const k of Object.keys(cur) as RowKey[]) {
      dirty[k] = cur[k] !== base[k];
    }
  }
  const dirtyCount = Object.values(dirty).filter(Boolean).length;
  const hasErrors = Object.keys(errs).length > 0;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setSaveErr(null);
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  const save = () => {
    if (!draft || hasErrors || saving) {
      return;
    }
    setSaving(true);
    setSaveErr(null);
    api
      .putSettings(toSettings(draft))
      .then((s) => {
        setSaved(s);
        setDraft(fromSettings(s));
        setSaving(false);
      })
      .catch(() => {
        setSaveErr("the server didn’t accept that — nothing was saved");
        setSaving(false);
      });
  };

  const revert = () => {
    if (saved) {
      setDraft(fromSettings(saved));
      setSaveErr(null);
    }
  };

  const jump = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const confirmWord = tenantHost || "delete";
  const f = draft;

  return (
    <main className="setpage">
      <div className="pagehead">
        <div className="crumb">yours / settings</div>
        <h1>Power user settings.</h1>
        <p className="sub">
          One power-user settings page: detection, diagnosis budgets, fix policy, oversight, spend
          caps, data deletion.
        </p>
      </div>

      <div className="cols">
        <nav className="anchors" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={current === s.id ? "current" : undefined}
              onClick={(e) => jump(e, s.id)}
            >
              <span className="t">{s.label}</span>
            </a>
          ))}
        </nav>

        <div className="content">
          {loadFailed ? (
            <Card className="sec-card">
              <Row
                label="Settings aren’t reachable right now."
                caption="This deployment couldn’t load them. Nothing here is editable until the server answers."
              />
            </Card>
          ) : null}

          {f ? (
            <>
              {/* ================= DETECTION ================= */}
              <section id="detection">
                <Kick kn="01">Detection</Kick>
                <Card className="sec-card">
                  <Row
                    label="Poll cadence"
                    caption="How often Darn asks Davis for new problems."
                    dirty={dirty.poll}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.poll}
                        onChange={(v) => set("poll", v)}
                        unit="s"
                        aria-label="Poll cadence"
                      />
                      {errs.poll ? (
                        <span className="err">{errs.poll}</span>
                      ) : (
                        <span className="hint">min 10 · max 300</span>
                      )}
                    </div>
                  </Row>

                  <Row
                    label="Problem scope"
                    caption="Which Davis problems wake Darn up."
                    top
                    dirty={dirty.scope}
                  >
                    <div className="ctl">
                      <Radios<ProblemScope>
                        value={f.scope}
                        onChange={(v) => set("scope", v)}
                        options={[
                          {
                            value: "deploy_linked",
                            ariaLabel: "Deploy-linked regressions only (default)",
                            label: (
                              <>
                                Deploy-linked regressions only{" "}
                                <span className="dflt">(default)</span>
                              </>
                            ),
                          },
                          {
                            value: "any_code_smell",
                            ariaLabel: "Any problem that smells like code",
                            label: <>Any problem that smells like code</>,
                          },
                        ]}
                      />
                    </div>
                  </Row>

                  <Row
                    label="Quiet hours"
                    caption="Darn still diagnoses at night — it just holds the PR until morning."
                    top
                    dirty={dirty.quiet}
                  >
                    <div className="ctl-col">
                      <Switch
                        on={f.quietOn}
                        onChange={(v) => set("quietOn", v)}
                        aria-label="Quiet hours"
                      />
                      <div className={f.quietOn ? "ctl-line" : "ctl-line dim"}>
                        <Field
                          value={f.quietStart}
                          onChange={(v) => set("quietStart", v)}
                          widthCh={5}
                          disabled={!f.quietOn}
                          aria-label="Quiet hours start"
                        />
                        <span className="arrow">→</span>
                        <Field
                          value={f.quietEnd}
                          onChange={(v) => set("quietEnd", v)}
                          widthCh={5}
                          disabled={!f.quietOn}
                          aria-label="Quiet hours end"
                        />
                        <SelectBox
                          value={f.quietTz}
                          options={TIMEZONES.map((tz) => ({ value: tz, label: tz }))}
                          onChange={(v) => set("quietTz", v)}
                          disabled={!f.quietOn}
                          aria-label="Quiet hours timezone"
                        />
                      </div>
                      {errs.quiet ? <span className="err">{errs.quiet}</span> : null}
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= DIAGNOSIS ================= */}
              <section id="diagnosis">
                <Kick kn="02">Diagnosis</Kick>
                <Card className="sec-card">
                  <Row
                    label="DQL budget per incident"
                    caption="Grail queries cost money. Cap them."
                    dirty={dirty.dqlBudget}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.dqlBudget}
                        onChange={(v) => set("dqlBudget", v)}
                        unit="queries"
                        aria-label="DQL budget per incident"
                      />
                      {errs.dqlBudget ? <span className="err">{errs.dqlBudget}</span> : null}
                    </div>
                  </Row>

                  <Row
                    label="Lookback window cap"
                    caption="How far back any single query may reach."
                    dirty={dirty.lookback}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.lookback}
                        onChange={(v) => set("lookback", v)}
                        unit="min"
                        aria-label="Lookback window cap"
                      />
                      {errs.lookback ? <span className="err">{errs.lookback}</span> : null}
                    </div>
                  </Row>

                  <Row label="Stop when it’s not code" caption="Not a setting. Darn never guesses.">
                    <div className="ctl">
                      <span className="locktag">locked on</span>
                      <Switch on locked aria-label="Stop when it’s not code" />
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= FIX POLICY ================= */}
              <section id="fix-policy">
                <Kick kn="03">Fix policy</Kick>
                <Card className="sec-card">
                  <Row
                    label="Branch prefix"
                    caption="Every fix branch Darn opens starts with this."
                    dirty={dirty.branchPrefix}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.branchPrefix}
                        onChange={(v) => set("branchPrefix", v)}
                        widthCh={Math.max(f.branchPrefix.length + 0.5, 6)}
                        alignLeft
                        aria-label="Branch prefix"
                      />
                      {errs.branchPrefix ? <span className="err">{errs.branchPrefix}</span> : null}
                    </div>
                  </Row>

                  <Row
                    label="PR labels"
                    caption="Stamped on every PR Darn opens."
                    top
                    dirty={dirty.labels}
                  >
                    <div className="ctl">
                      <ChipsInput
                        chips={f.labels}
                        onChange={(chips) => set("labels", chips)}
                        placeholder="add label…"
                        aria-label="Add PR label"
                      />
                    </div>
                  </Row>

                  <Row
                    label="Draft PRs"
                    caption="Open PRs as drafts if your team gates CI on review."
                    dirty={dirty.draftPrs}
                  >
                    <div className="ctl">
                      <Switch
                        on={f.draftPrs}
                        onChange={(v) => set("draftPrs", v)}
                        aria-label="Draft PRs"
                      />
                    </div>
                  </Row>

                  <Row
                    label="Max changed files · Max diff lines"
                    caption="Bigger than this isn’t a mend, it’s a rewrite. Darn declines and says why."
                    dirty={dirty.maxSize}
                  >
                    <div className="ctl-col">
                      <div className="ctl">
                        <Field
                          value={f.maxFiles}
                          onChange={(v) => set("maxFiles", v)}
                          unit="files"
                          aria-label="Max changed files"
                        />
                        <Field
                          value={f.maxLines}
                          onChange={(v) => set("maxLines", v)}
                          unit="lines"
                          aria-label="Max diff lines"
                        />
                      </div>
                      {errs.maxSize ? <span className="err">{errs.maxSize}</span> : null}
                    </div>
                  </Row>

                  <Row
                    label="Path denylist"
                    caption="Places robots shouldn’t sew."
                    top
                    dirty={dirty.denylist}
                  >
                    <div className="ctl">
                      <textarea
                        className="ta"
                        rows={Math.max(3, f.denylist.split("\n").length)}
                        spellCheck={false}
                        aria-label="Path denylist"
                        value={f.denylist}
                        onChange={(e) => set("denylist", e.target.value)}
                      />
                    </div>
                  </Row>

                  <Row label="One open PR per service" caption="No PR storms. Ever.">
                    <div className="ctl">
                      <span className="locktag">locked on</span>
                      <Switch on locked aria-label="One open PR per service" />
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= OVERSIGHT ================= */}
              <section id="oversight">
                <Kick kn="04">Oversight</Kick>
                <Card className="sec-card">
                  <Row
                    label="Merge authority"
                    caption={
                      <>
                        Never. A human with merge rights approves on GitHub.{" "}
                        <span className="nb">This switch exists to show you it’s off.</span>
                      </>
                    }
                  >
                    <div className="ctl">
                      <span className="swlab">Darn can merge</span>
                      <span className="locktag">locked off</span>
                      <Switch on={false} locked aria-label="Darn can merge" />
                    </div>
                  </Row>

                  <Row
                    label="Decline behavior"
                    caption="On decline, close the branch and tidy up."
                    dirty={dirty.declineTidy}
                  >
                    <div className="ctl">
                      <Switch
                        on={f.declineTidy}
                        onChange={(v) => set("declineTidy", v)}
                        aria-label="Decline behavior"
                      />
                    </div>
                  </Row>

                  <Row
                    label="Webhook"
                    caption={
                      <>
                        One webhook, fired when a PR opens and when it closes.{" "}
                        <span className="nb">Point it anywhere.</span>
                      </>
                    }
                    dirty={dirty.webhook}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.webhook}
                        onChange={(v) => set("webhook", v)}
                        widthCh={21}
                        alignLeft
                        placeholder="https://"
                        aria-label="Webhook URL"
                      />
                      {errs.webhook ? <span className="err">{errs.webhook}</span> : null}
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= BUDGETS ================= */}
              <section id="budgets">
                <Kick kn="05">Budgets</Kick>
                <Card className="sec-card">
                  <Row
                    label="Token budget per fix"
                    caption={
                      <>
                        Gemini stops mid-thought rather than blowing the budget;{" "}
                        <span className="nb">the incident says ‘budget reached’.</span>
                      </>
                    }
                    dirty={dirty.tokenBudget}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.tokenBudget}
                        onChange={(v) => set("tokenBudget", v)}
                        unit="tokens"
                        aria-label="Token budget per fix"
                      />
                      {errs.tokenBudget ? <span className="err">{errs.tokenBudget}</span> : null}
                    </div>
                  </Row>

                  <Row
                    label="Monthly spend cap"
                    caption="At the cap, Darn pauses watching and tells you on the Your watch page."
                    dirty={dirty.spendCap}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.spendCap}
                        onChange={(v) => set("spendCap", v)}
                        unitBefore="$"
                        aria-label="Monthly spend cap"
                      />
                      {errs.spendCap ? <span className="err">{errs.spendCap}</span> : null}
                    </div>
                  </Row>

                  <Row
                    label="Grail query budget per day"
                    caption="Across every incident, per calendar day."
                    dirty={dirty.dqlDay}
                  >
                    <div className="ctl-col">
                      <Field
                        value={f.dqlDay}
                        onChange={(v) => set("dqlDay", v)}
                        unit="queries"
                        aria-label="Grail query budget per day"
                      />
                      {errs.dqlDay ? <span className="err">{errs.dqlDay}</span> : null}
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= DATA & PRIVACY ================= */}
              <section id="data-privacy">
                <Kick kn="06">Data &amp; privacy</Kick>
                <Card className="sec-card">
                  <Row
                    label="What Darn stores"
                    top
                    wideLeft
                    leftExtra={
                      <>
                        <ul className="stores">
                          <li>Incident records and their receipts</li>
                          <li>service↔repo mappings</li>
                          <li>your tokens (Secret Manager only)</li>
                        </ul>
                        <div className="stores-tail">
                          Nothing else. The shop’s telemetry stays in Dynatrace.
                        </div>
                      </>
                    }
                  />

                  <Row
                    label="Retention"
                    caption={
                      <>
                        Or <span className="mono">30 / 90 / 365</span> days.
                      </>
                    }
                    dirty={dirty.retention}
                  >
                    <div className="ctl">
                      <SelectBox
                        value={f.retention}
                        options={RETENTION_OPTIONS}
                        onChange={(v) => set("retention", v as Retention)}
                        aria-label="Retention"
                      />
                    </div>
                  </Row>

                  <Row
                    label="Delete all stored incidents"
                    caption={
                      <>
                        You’ll type the tenant host to confirm.{" "}
                        <span className="nb">Every stored incident and its receipts, gone.</span>
                      </>
                    }
                  >
                    <div className="ctl">
                      <BtnGhost size="sm" onClick={() => setModal("incidents")}>
                        Delete all stored incidents…
                      </BtnGhost>
                    </div>
                  </Row>

                  <Row
                    label="Delete tokens now"
                    caption={
                      <>
                        You’ll type the tenant host to confirm.{" "}
                        <span className="nb">Removed from Secret Manager immediately.</span>
                      </>
                    }
                  >
                    <div className="ctl">
                      <BtnGhost size="sm" onClick={() => setModal("tokens")}>
                        Delete tokens now…
                      </BtnGhost>
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= THE MEDIC ================= */}
              <section id="the-medic">
                <Kick kn="07">The medic</Kick>
                <Card className="sec-card">
                  <Row
                    label="Self-traces"
                    caption={
                      <>
                        Darn’s own traces ship to YOUR tenant.{" "}
                        <span className="nb">The medic doesn’t get to take off the monitor.</span>
                      </>
                    }
                  >
                    <div className="ctl">
                      <span className="locktag">locked on</span>
                      <Switch on locked aria-label="Self-traces" />
                    </div>
                  </Row>

                  <Row
                    label="Share timings with the public demo"
                    caption={
                      <>
                        Anonymized stage timings only, to make the public demo’s numbers honest.{" "}
                        <span className="nb">Off unless you say so.</span>
                      </>
                    }
                    dirty={dirty.shareTimings}
                  >
                    <div className="ctl">
                      <Switch
                        on={f.shareTimings}
                        onChange={(v) => set("shareTimings", v)}
                        aria-label="Share timings with the public demo"
                      />
                    </div>
                  </Row>
                </Card>
              </section>

              {/* ================= STICKY SAVE BAR ================= */}
              {dirtyCount > 0 ? (
                <div className="savebar">
                  <div className="note">
                    <span className="tick" />
                    {dirtyCount} unsaved change{dirtyCount === 1 ? "" : "s"}
                    {saveErr ? <span className="err">· {saveErr}</span> : null}
                  </div>
                  <div className="acts">
                    <BtnGhost onClick={revert}>Revert</BtnGhost>
                    <BtnInk onClick={save} disabled={hasErrors || saving}>
                      Save changes
                    </BtnInk>
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      {modal === "incidents" ? (
        <ConfirmModal
          title="Delete all stored incidents"
          lead="Every stored incident and its receipts, gone. The PRs on your repo stay yours."
          confirmWord={confirmWord}
          confirmLabel="Delete all stored incidents"
          onConfirm={() => postDelete("/api/settings/delete-incidents")}
          onClose={() => setModal(null)}
        />
      ) : null}
      {modal === "tokens" ? (
        <ConfirmModal
          title="Delete tokens now"
          lead="Removed from Secret Manager immediately. Darn stops watching until you connect again."
          confirmWord={confirmWord}
          confirmLabel="Delete tokens now"
          onConfirm={() => postDelete("/api/settings/delete-tokens")}
          onClose={() => setModal(null)}
        />
      ) : null}
    </main>
  );
}
