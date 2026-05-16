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
