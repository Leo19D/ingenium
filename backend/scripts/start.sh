#!/usr/bin/env bash
# Production start (Railway): bootstrap baze pa pokreni server.
# 1 worker po defaultu — in-process scheduler smije raditi samo u jednom procesu
# (inače bi svaki worker imao svoj scheduler). Override preko WEB_CONCURRENCY.
set -euo pipefail

echo "→ Bootstrap baze..."
python -m scripts.init_db

echo "→ Pokrećem uvicorn (workers=${WEB_CONCURRENCY:-1})..."
# --proxy-headers: čitaj X-Forwarded-For (pravi IP korisnika iza Railway LB-a /
# Vercel proxyja) za rate limiter + login security alert.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers \
  --forwarded-allow-ips '*'
