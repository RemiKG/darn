# Trafficbot image — built from the trafficbot/ context:
#   gcloud run deploy darn-trafficbot --source trafficbot
#
# This is a WORKER, not a web service: it generates steady synthetic traffic
# against SHOP_URL so Davis has signal to watch. Cloud Run notes:
#   - deploy WITHOUT --allow-unauthenticated (nothing should call it),
#   - WITH --no-cpu-throttling (the loop needs CPU between "requests" — it
#     never receives any),
#   - WITH --min-instances 1 (the instance must stay up to keep shopping).
# Cloud Run still startup-probes $PORT, so the bot's tiny /healthz server is
# bound to the injected PORT below (local default stays 4603).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py ./bot.py

RUN useradd --create-home --uid 10001 bot
USER bot

# bot.py reads HEALTH_PORT for its /healthz listener; map Cloud Run's PORT
# onto it so the revision passes the startup probe.
CMD HEALTH_PORT=${PORT:-${HEALTH_PORT:-4603}} exec python bot.py
