# Loose Threads shop image — built from the shop/ context:
#   gcloud run deploy loose-threads-shop --source shop
#
# A deliberately small, real FastAPI storefront. State is in-memory by design
# (it is a prop); the deployed instance keeps it for the life of the revision.
# Sabotage arrives as real commits to app/*.py — CI rebuilds + redeploys this
# image, which is exactly how the tear reaches production.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The whole shop lives in app/ (templates and static files included).
COPY app ./app

RUN useradd --create-home --uid 10001 shop
USER shop

# Cloud Run injects PORT (local default 4602 per the repo contract).
# app/main.py exposes `app`; uvicorn is the entrypoint.
EXPOSE 4602
CMD exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-4602}
