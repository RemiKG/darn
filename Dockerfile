# Darn server image — built from the REPO ROOT context:
#   gcloud run deploy darn --source .
#
# Multi-stage: stage 1 builds the web bundle, stage 2 is the Python runtime.
# The runtime layout mirrors the monorepo, because the server resolves its
# sibling directories relative to its own files:
#   server/app/main.py          -> parents[2]/web/dist   => /app/web/dist
#   server/app/demo/defects.py  -> parents[3]/shop/defects => /app/shop/defects
# No secrets are baked in — all config is env vars set on the Cloud Run service.

# ---------------------------------------------------------------- stage 1: web
FROM node:22-slim AS webbuild
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# "build" runs tsc --noEmit && vite build -> /build/web/dist
RUN npm run build

# ------------------------------------------------------------ stage 2: runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/server

# Dependencies first (layer cache survives app-code changes).
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The server package itself.
COPY server/app ./app

# Defect patch payloads — app/demo/defects.py reads <repo root>/shop/defects.
COPY shop/defects /app/shop/defects

# Built web bundle — app/main.py serves <repo root>/web/dist with SPA fallback.
COPY --from=webbuild /build/web/dist /app/web/dist

# Non-root runtime user; everything the app touches is read-only on disk
# (state lives in memory or Firestore, never on the container filesystem).
RUN useradd --create-home --uid 10001 darn
USER darn

# Cloud Run injects PORT; app/main.py binds it (local default 4601).
# Deploy with --min-instances 1 --no-cpu-throttling: the Davis problem poller
# and incident timers run as background asyncio tasks between requests.
EXPOSE 4601
CMD ["python", "-m", "app.main"]
