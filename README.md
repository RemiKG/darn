# Darn.

**Fixes with receipts.** When a deploy tears a hole in production, Darn finds the
exact commit, writes the fix, and opens a pull request where every claim is a
receipt you can re-run in Dynatrace.

*Don't trust a robot in production. Trust the receipts.*

Darn is an agent that **acts** — and proves it. Davis (Dynatrace's AI) raises the
problem before the agent moves. Darn diagnoses through the **Dynatrace MCP
server** with budgeted DQL forensics, intersects failure onset with deploy
events, blames the exact commit hunk, has **Gemini on Vertex AI** write the fix,
and opens a PR whose body is an evidence dossier. A human approves — Darn never
merges by itself. "Fixed" means the previously failing request now succeeds,
error rate recovered via DQL, and **the Davis problem closed** — the referee
says it's mended, not the agent. And the agent itself ships its own OpenTelemetry
traces to the same tenant: *the medic wears a heart monitor.*

## How it fits together

```
repo/
├── web/          Darn's frontend — Vite + React + TypeScript.
│                 Five pages: the shop floor (landing + demo), the incident
│                 receipt ledger, "use it on yours" (BYO wizard), settings, 404.
│                 Live updates over Server-Sent Events. Built to web/dist.
├── server/       Darn's backend + the agent — Python / FastAPI.
│   ├── app/api/           REST + SSE endpoints (/api/*)
│   ├── app/demo/          demo orchestrator: single-incident lock, the needle,
│   │                      spectator presence, cooldown, auto-revert timers
│   ├── app/agent/         the Google ADK agent pipeline (detect → diagnose →
│   │                      fix → PR → verify), receipts, medic recorder, OTel
│   ├── app/integrations/  Dynatrace MCP gateway client, GitHub (App or PAT),
│   │                      Gemini on Vertex AI, Dynatrace Events API
│   └── app/store/         persistence: Firestore (deployed) or memory (dev)
│                 In production the server also serves web/dist (one service).
├── shop/         "Loose Threads" — the sock shop that gets broken on purpose.
│                 Real FastAPI service (catalog/cart/checkout/pay/inventory),
│                 OpenTelemetry-instrumented to Dynatrace. Its storefront is a
│                 deliberately small, charming page. The socks are not real.
│                 shop/defects/ holds the four pre-authored sabotage patches.
├── trafficbot/   Synthetic shoppers — steady traffic so Davis has signal.
│                 (~10% empty-cart checkouts: exactly what one defect breaks.)
└── .github/      CI: PR checks (the checks on Darn's PRs) and deploys to
                  Cloud Run, with a Dynatrace deployment marker per deploy.
```

The pipeline, concretely: the server polls **`query-problems`** on the Dynatrace
MCP gateway. When Davis raises a problem on a watched service, the agent runs
budgeted forensics via **`execute-dql`** (failure rate by endpoint, exception +
stack frames, onset timestamp), intersects onset with deployment events and
GitHub commit history (compare API), matches the failing stack frame to the
deploy's diff to isolate the suspect hunk, briefs **Gemini (Vertex AI)** with
the receipts to write a minimal diff, and opens a PR whose body carries every
DQL block copy-pasteable. After a human approves and CI redeploys, Darn replays
the failing request, re-runs recovery DQL, waits for the Davis problem to
close, posts the closure evidence on the PR, and sends a deployment annotation.
Every external call lands in the medic trace (and, when ingest is configured,
as OTel spans in the same Dynatrace tenant).

## Run it locally

Prereqs: Python 3.12+, Node 20+.

```bash
# the server (API + serves the built web)
cd server
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests -q     # 65 tests
.venv/Scripts/python -m app.main            # http://localhost:4601

# the web app
cd web
npm install
npm run build        # production bundle the server serves at :4601
npm run dev          # or: live dev server at http://localhost:4600 (proxies /api)

# the shop
cd shop
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m app.main             # http://localhost:4602

# synthetic shoppers (optional)
cd trafficbot
pip install -r requirements.txt
SHOP_URL=http://localhost:4602 python bot.py
```

With no environment configured the server runs in an **honest not-configured
mode**: the health card says telemetry isn't connected, the tear button
explains what's missing, and nothing is faked. Wire the env vars below and the
same build does the real thing.

## Environment variables

### Darn server (`server/`)

| Variable | Required | Default | What it does |
|---|---|---|---|
| `PORT` | – | `4601` | Listen port (Cloud Run injects it) |
| `PUBLIC_BASE_URL` | – | – | Public URL of Darn (used in PR-body links) |
| `DT_ENVIRONMENT` | for Dynatrace | – | `https://<env>.apps.dynatrace.com` |
| `DT_PLATFORM_TOKEN` | for Dynatrace | – | Platform token (MCP gateway Bearer). Scopes: `mcp-gateway:servers:invoke`, `mcp-gateway:servers:read`, `storage:buckets:read`, `storage:spans:read`, `storage:logs:read`, `storage:metrics:read`, `storage:events:read`, `storage:entities:read` |
| `DT_MCP_URL` | – | derived | Override the MCP gateway URL |
| `DT_API_TOKEN` | optional | – | Classic access token (ingest scopes) — enables deployment annotations + the agent's own OTel traces |
| `DT_CLASSIC_URL` | – | derived | `https://<env>.live.dynatrace.com` override |
| `GOOGLE_CLOUD_PROJECT` | for Gemini | – | GCP project (Vertex AI + Firestore + Secret Manager) |
| `GOOGLE_CLOUD_LOCATION` | – | `global` | Vertex location (`gemini-3-flash-preview` lives on `global`) |
| `GEMINI_MODEL` | – | `gemini-3-flash-preview` | The fix-writing model |
| `GEMINI_PRICE_IN_PER_1M` / `GEMINI_PRICE_OUT_PER_1M` | – | – | USD per 1M tokens; when both set, incidents show measured cost (omitted otherwise — never invented) |
| `GITHUB_REPO` | for demo path | – | `owner/name` of the public repo (this one) |
| `GITHUB_TOKEN` | or App vars | – | PAT with Contents r/w + Pull requests r/w |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_B64`, `GITHUB_APP_INSTALLATION_ID` | for BYO | – | GitHub App credentials (preferred over PAT when present) |
| `STORE` | – | auto | `firestore` when a GCP project is set, else `memory` |
| `FIRESTORE_DATABASE` | – | `(default)` | Firestore database id |
| `SECRETS_BACKEND` | – | auto | `gcp` (Secret Manager) when a project is set, else `memory` |
| `SHOP_URL` | for verify | – | Public URL of the Loose Threads shop (replay checks) |
| `DEMO_SERVICE_NAME` | – | `loose-threads-shop` | The shop's service name in Dynatrace |
| `POLL_SECONDS` | – | `30` | Davis poll cadence |
| `COOLDOWN_SECONDS` | – | `180` | Pause between demo incidents |
| `NEEDLE_LAPSE_SECONDS` | – | `90` | Holder absence before the needle frees |
| `APPROVE_TIMEOUT_SECONDS` | – | `600` | No approval → auto-revert |
| `DQL_BUDGET_PER_INCIDENT` | – | `12` | Hard cap on Grail queries per diagnosis |
| `OTEL_ENABLED` | – | auto | Agent self-traces (on when `DT_API_TOKEN` set) |
| `OTEL_SERVICE_NAME` | – | `darn-agent` | Service name for the medic's own traces |

### Shop (`shop/`)

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `4602` | Listen port |
| `DARN_URL` | – | Darn's public URL (the "Darn is on it →" banner) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | – | `https://<env>.live.dynatrace.com/api/v2/otlp` |
| `OTEL_EXPORTER_OTLP_HEADERS` | – | `Authorization=Api-Token <DT_API_TOKEN>` |
| `OTEL_SERVICE_NAME` | `loose-threads-shop` | Service name Davis watches |

### Traffic bot (`trafficbot/`)

| Variable | Default | What it does |
|---|---|---|
| `SHOP_URL` | – | The shop to shop at |
| `RATE_RPM` | `180` | Requests per minute |
| `JITTER` | `0.3` | Timing jitter fraction |
| `HEALTH_PORT` | – | Optional `/healthz` port (e.g. `4603`) |

## Deploy (Google Cloud Run)

Three services from this one repo (region `us-central1` assumed):

```bash
gcloud run deploy darn --source . --region us-central1 --allow-unauthenticated \
  --min-instances 1 --no-cpu-throttling
gcloud run deploy loose-threads-shop --source shop --region us-central1 \
  --allow-unauthenticated
gcloud run deploy darn-trafficbot --source trafficbot --region us-central1 \
  --no-cpu-throttling --min-instances 1
```

`darn` needs `--min-instances 1 --no-cpu-throttling` (the Davis poller and demo
timers are background tasks in the process). The repo ships without `web/dist`
— the root Dockerfile builds the web bundle fresh inside the image. Set the
env vars on each service (see above); secrets belong in
Secret Manager–backed env vars, never in the image. The deploy workflow in
`.github/workflows/deploy.yml` does the same on every push to `main` — which is
exactly how a demo sabotage commit reaches production through the real CI.

GitHub Actions expects: `GCP_SA_KEY` (service-account JSON with Cloud Run +
Cloud Build roles), `GCP_PROJECT`, and optionally `DT_CLASSIC_URL` +
`DT_API_TOKEN` for deployment markers.

## What is REAL (and what is staged)

Real, end to end: the Dynatrace tenant and Davis problems; every MCP tool call;
the bad commits, CI runs and deploys; the public-repo PRs and diffs; closure
verification (replay + recovery DQL + Davis problem closed); the agent's own
OTel traces; the bring-your-own-tenant path; every published number (wall
clocks, DQL counts, token costs — measured per incident, shown with the
incident).

Staged by design, and labeled as such in the UI: the sabotage menu (four
pre-authored bad commits — real commits through the real pipeline), the
synthetic shopper traffic, and the sock shop itself. Demo mechanics
(single-incident lock, the needle, cooldown) keep the public repo tidy between
incidents. Anything that can't be real is removed rather than faked.

## License

MIT — see [LICENSE](LICENSE).
