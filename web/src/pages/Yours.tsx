/**
 * USE IT ON YOURS — /yours.
 *
 * Two faces, swapped live without a reload:
 *   WIZARD     (not connected) — three step cards on the stitched progress
 *              thread: Connect Dynatrace → Install the GitHub App → Map
 *              services (+ the essential deploy-markers panel).
 *   YOUR WATCH (connected)     — mappings as cards-rows, "Your mends" strip,
 *              and the ink-bordered (never red) Disconnect-and-delete card
 *              with its typed-confirm modal.
 *
 * Everything live comes from api.yours.*; nothing is invented. Where the
 * contract has no field (default branch, PR link lists) the UI shows a form
 * default or derives from the mends — see component notes.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  type ByoService,
  type GithubInstallUrl,
  type YoursState,
} from "../lib/api";
import Card from "../components/Card";
import { Pill } from "../components/Pills";
import { BtnGhost, BtnGhostInk, BtnInk } from "../components/Buttons";
import { WizardThread, type ThreadState } from "../components/Thread";
import MapServices, { type MapRow } from "../components/yours/MapServices";
import WatchView from "../components/yours/WatchView";
import DisconnectModal from "../components/yours/DisconnectModal";
import { cx } from "../lib/cx";
import "../styles/pages/yours.css";

type Mode = "loading" | "wizard" | "watch";
type StepNo = 1 | 2 | 3;

const GITHUB_POLL_MS = 4_000;

/** Server hint out of an error (422 {error, hint}) — calm, verbatim. */
function hintOf(e: unknown): string {
  if (e instanceof ApiError && e.body && typeof e.body === "object") {
    const b = e.body as Record<string, unknown>;
    if (typeof b.hint === "string" && b.hint) {
      return b.hint;
    }
    if (typeof b.error === "string" && b.error) {
      return b.error;
    }
  }
  return e instanceof Error ? e.message : String(e);
}

/** Wrap *.dynatrace.com hostnames in mono — as the failure row does. */
function monoHosts(text: string): ReactNode[] {
  return text
    .split(/([a-z0-9-]+(?:\.[a-z0-9-]+)*\.dynatrace\.com)/g)
    .map((part, i) =>
      part.endsWith(".dynatrace.com") ? (
        <span className="mono" key={i}>
          {part}
        </span>
      ) : (
        part
      )
    );
}

function LockGlyph() {
  return (
    <svg width="14" height="16" viewBox="0 0 14 16" fill="none" aria-hidden="true">
      <rect x="1" y="6.5" width="12" height="8.5" rx="2.5" fill="#1B2A44" />
      <path d="M3.8 6.5V4.6a3.2 3.2 0 0 1 6.4 0v1.9" stroke="#1B2A44" strokeWidth="1.8" fill="none" />
      <circle cx="7" cy="10.4" r="1.2" fill="#F5F3EF" />
    </svg>
  );
}

const SCOPES = [
  "app-engine:apps:run",
  "storage:buckets:read",
  "storage:logs:read",
  "storage:metrics:read",
  "storage:spans:read",
  "davis:problems:read",
  "openpipeline:events.ingest",
];

function StepHead({ n, title, state }: { n: number; title: string; state: ThreadState }) {
  return (
    <div className="stephead">
      <div className={cx("medal", state)}>{state === "done" ? "✓" : <span className="num">{n}</span>}</div>
      <h2>
        Step <span className="num">{n}</span> — {title}
      </h2>
      {state === "done" ? (
        <Pill kind="ok">Done</Pill>
      ) : state === "active" ? (
        <Pill kind="amber">Active</Pill>
      ) : (
        <Pill kind="neutral">Pending</Pill>
      )}
    </div>
  );
}

export default function Yours() {
  const [mode, setMode] = useState<Mode>("loading");
  const [yours, setYours] = useState<YoursState | null>(null);
  const [installInfo, setInstallInfo] = useState<GithubInstallUrl | null>(null);

  // ------------------------------------------------------------ wizard state
  const [step, setStep] = useState<StepNo>(1);
  const [tenantUrl, setTenantUrl] = useState("");
  const [token, setToken] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [services, setServices] = useState<ByoService[] | null>(null);
  const [connectHint, setConnectHint] = useState<string | null>(null);
  const [github, setGithub] = useState<{ installed: boolean; repo: string } | null>(null);
  const [rows, setRows] = useState<MapRow[]>([]);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // ------------------------------------------------------- disconnect modal
  const [modalOpen, setModalOpen] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const resetWizard = useCallback(() => {
    setStep(1);
    setTenantUrl("");
    setToken("");
    setConnecting(false);
    setServices(null);
    setConnectHint(null);
    setRows([]);
    setStarting(false);
    setStartError(null);
  }, []);

  // ------------------------------------------------------------- first load
  useEffect(() => {
    let stale = false;
    void Promise.all([
      api.getYours().catch(() => null),
      api.yoursGithubInstallUrl().catch(() => null),
    ]).then(([y, install]) => {
      if (stale) {
        return;
      }
      setInstallInfo(install ?? { url: null, configured: false });
      if (y?.connected) {
        setYours(y);
        setMode("watch");
      } else {
        if (y) {
          setGithub(y.github);
        }
        setMode("wizard");
      }
    });
    return () => {
      stale = true;
    };
  }, []);

  // -------------------------------------- step 2: poll for the App install
  const githubConfigured = installInfo?.configured ?? false;
  const installed = !!github?.installed && !!github.repo;
  useEffect(() => {
    if (mode !== "wizard" || step !== 2 || !githubConfigured || installed) {
      return;
    }
    let stop = false;
    const tick = () => {
      api
        .getYours()
        .then((y) => {
          if (!stop) {
            setGithub(y.github);
          }
        })
        .catch(() => {
          /* polling is best-effort */
        });
    };
    tick();
    const interval = setInterval(tick, GITHUB_POLL_MS);
    const onFocus = () => tick();
    window.addEventListener("focus", onFocus);
    return () => {
      stop = true;
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [mode, step, githubConfigured, installed]);

  // ------------------------------------------------------------- step 1 act
  const testConnection = () => {
    if (connecting) {
      return;
    }
    setConnecting(true);
    setConnectHint(null);
    setServices(null);
    api
      .yoursConnect(tenantUrl.trim(), token)
      .then((res) => {
        setServices(res.services);
        setRows(res.services.map((s) => ({ service: s.name, health: s.health, repo: "", watch: false })));
      })
      .catch((e: unknown) => setConnectHint(hintOf(e)))
      .finally(() => setConnecting(false));
  };

  // ------------------------------------------------------------- step 3 act
  const repoName = installed ? github?.repo ?? "" : "";
  const branch = installed ? "main" : "";

  const postMappings = useCallback(
    async (mapRows: MapRow[]) => {
      for (const r of mapRows) {
        await api.yoursMapping({ service: r.service, repo: r.repo, branch: branch || "main", watch: r.watch });
      }
      const y = await api.getYours();
      setYours(y);
    },
    [branch]
  );

  const startWatching = () => {
    if (starting) {
      return;
    }
    setStarting(true);
    setStartError(null);
    postMappings(rows.filter((r) => r.repo))
      .then(() => setMode("watch"))
      .catch((e: unknown) => setStartError(hintOf(e)))
      .finally(() => setStarting(false));
  };

  // ----------------------------------------------------------- watch actions
  const refreshYours = useCallback(async () => {
    const y = await api.getYours();
    setYours(y);
  }, []);

  const pauseService = useCallback(
    async (service: string) => {
      await api.yoursPause(service).catch(() => undefined);
      await refreshYours().catch(() => undefined);
    },
    [refreshYours]
  );

  const unmapService = useCallback(
    async (service: string) => {
      // There is no unmap endpoint — posting the mapping back
      // with an empty repo and watch:false is the removal shape.
      await api.yoursMapping({ service, repo: "", branch: "", watch: false }).catch(() => undefined);
      await refreshYours().catch(() => undefined);
    },
    [refreshYours]
  );

  const addMappings = useCallback(
    async (mapRows: MapRow[]) => {
      for (const r of mapRows) {
        await api.yoursMapping({ service: r.service, repo: r.repo, branch: "main", watch: r.watch });
      }
      await refreshYours();
    },
    [refreshYours]
  );

  const disconnect = (confirmHost: string) => {
    setDisconnecting(true);
    setDisconnectError(null);
    api
      .yoursDisconnect(confirmHost)
      .then(() => {
        setModalOpen(false);
        setYours(null);
        resetWizard();
        setMode("wizard");
      })
      .catch((e: unknown) => setDisconnectError(hintOf(e)))
      .finally(() => setDisconnecting(false));
  };

  // --------------------------------------------------------------- wizard ui
  const stateOf = (n: StepNo): ThreadState => (step === n ? "active" : step > n ? "done" : "pending");
  const wizardSteps = useMemo(
    () =>
      (["Connect Dynatrace", "Install the GitHub App", "Map services"] as const).map((label, i) => {
        const s = stateOf((i + 1) as StepNo);
        return { label, state: s, stateLabel: s };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [step]
  );

  const tokenRef = useRef<HTMLInputElement>(null);

  if (mode === "loading") {
    return <main className="wrap yours" />;
  }

  // ============================================================== YOUR WATCH
  if (mode === "watch" && yours) {
    return (
      <main className="wrap yours">
        <WatchView yours={yours} onPause={pauseService} onUnmap={unmapService} onAddMappings={addMappings} />

        <div className="danger">
          <h3>Disconnect and delete</h3>
          <p>
            Removes your tokens from Secret Manager and deletes every stored incident and mapping.
            The PRs on your repo stay yours.
          </p>
          <div className="row">
            <BtnGhostInk
              size="sm"
              onClick={() => {
                setDisconnectError(null);
                setModalOpen(true);
              }}
            >
              Disconnect and delete…
            </BtnGhostInk>
            <span className="hint">typed confirmation — type the tenant host</span>
          </div>
        </div>

        {modalOpen ? (
          <DisconnectModal
            tenantHost={yours.tenant_host}
            busy={disconnecting}
            error={disconnectError}
            onCancel={() => setModalOpen(false)}
            onConfirm={disconnect}
          />
        ) : null}
      </main>
    );
  }

  // ================================================================== WIZARD
  return (
    <main className="wrap yours">
      <div className="pagehead">
        <h1>Use it on yours.</h1>
        <p className="sub">The demo is the toy. This is the tool. Three steps, fully reversible.</p>
        <p className="scope">
          Darn watches deploy-linked regressions in code. Infra outages get evidence and a full
          stop — never a guess.
        </p>
      </div>

      <WizardThread steps={wizardSteps} />

      {/* ===== Step 1 — Connect Dynatrace ===== */}
      <Card className={cx("step", stateOf(1) === "active" && "activecard")}>
        <StepHead n={1} title="Connect Dynatrace" state={stateOf(1)} />

        <div className="fields">
          <div className="field">
            <label htmlFor="tenant-url">Tenant URL</label>
            <input
              id="tenant-url"
              className="input"
              type="text"
              placeholder="https://abc12345.apps.dynatrace.com"
              value={tenantUrl}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setTenantUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  tokenRef.current?.focus();
                }
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="platform-token">Platform token</label>
            <input
              id="platform-token"
              ref={tokenRef}
              className="input"
              type="password"
              placeholder=""
              value={token}
              autoComplete="off"
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  testConnection();
                }
              }}
            />
          </div>
        </div>

        <p className="helper">
          Mint a platform token in your tenant → Access Tokens. Darn needs exactly these scopes:
        </p>
        <div className="chips">
          {SCOPES.map((scope) => (
            <span className="chip" key={scope}>
              {scope}
            </span>
          ))}
          <span className="tail">— and nothing else.</span>
        </div>

        <div className="lockrow">
          <LockGlyph />
          Stored in Google Secret Manager. Deletable from Settings at any time.
        </div>

        <div className="actions">
          <BtnInk size="sm" onClick={testConnection} disabled={connecting || !tenantUrl.trim() || !token}>
            {connecting ? "Testing…" : "Test connection"}
          </BtnInk>
          {services ? (
            <span className="okrow">
              <span className="tick">✓</span>Connected.{" "}
              <span className="num">{services.length}</span> monitored services visible.
            </span>
          ) : null}
          {services ? (
            <BtnGhost size="sm" className="pushright" onClick={() => setStep(2)}>
              Continue
            </BtnGhost>
          ) : null}
        </div>

        {connectHint ? (
          <div className="errrow">
            <span className="msg">{monoHosts(connectHint)}</span>
          </div>
        ) : null}
      </Card>

      {/* ===== Step 2 — Install the GitHub App ===== */}
      <Card className={cx("step", stateOf(2) === "active" && "activecard")}>
        <StepHead n={2} title="Install the GitHub App" state={stateOf(2)} />

        <p className="stepcopy">
          Install Darn on the repo that deploys the service. Darn opens pull requests; it never
          pushes to your default branch.
        </p>

        <ul className="perm">
          <li>
            <span>
              <b>Contents</b> — read &amp; write <span className="why">(create fix branches)</span>
            </span>
          </li>
          <li>
            <span>
              <b>Pull requests</b> — write <span className="why">(open PRs, post closure evidence)</span>
            </span>
          </li>
          <li>
            <span>
              <b>Metadata</b> — read
            </span>
          </li>
        </ul>

        <div className="actions">
          {githubConfigured && installInfo?.url ? (
            <BtnInk size="sm" href={installInfo.url} target="_blank">
              Install on GitHub →
            </BtnInk>
          ) : (
            <BtnInk size="sm" disabled>
              Install on GitHub →
            </BtnInk>
          )}
          {installed ? (
            <span className="okrow">
              <span className="tick">✓</span>Installed on {github?.repo}
            </span>
          ) : null}
          {step >= 2 && (installed || !githubConfigured) ? (
            <BtnGhost size="sm" className="pushright" onClick={() => setStep(3)}>
              Continue
            </BtnGhost>
          ) : null}
        </div>

        {!githubConfigured ? (
          <div className="notewell">
            The GitHub App isn&rsquo;t configured on this deployment yet — the demo path
            doesn&rsquo;t need it; bring-your-own does.
          </div>
        ) : null}
      </Card>

      {/* ===== Step 3 — Map services ===== */}
      <Card className={cx("step", stateOf(3) === "active" && "activecard")}>
        <StepHead n={3} title="Map services" state={stateOf(3)} />
        <MapServices
          rows={rows}
          onRows={setRows}
          repo={repoName}
          branch={branch}
          canMap={installed && rows.length > 0}
          busy={starting}
          onStart={startWatching}
          error={startError}
        />
      </Card>
    </main>
  );
}
