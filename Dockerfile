# syntax=docker/dockerfile:1.7
# Root Dockerfile za Railway — jedan servis koji servira API + frontend + login
# (isti origin, bez CORS/login-split komplikacija). Build context = repo root.
# DB = Supabase (DATABASE_URL env). Frontend kasnije može na Vercel (API_BASE konfig).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: PDF parsing (poppler), OCR (tesseract), psql client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git libpq-dev \
    poppler-utils ghostscript \
    libgl1 libglib2.0-0 \
    fonts-liberation \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-hrv tesseract-ocr-deu tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml backend/README.md /app/
RUN pip install .

COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/
COPY backend/scripts /app/scripts
COPY frontend /app/static_frontend

RUN chmod +x /app/scripts/start.sh \
    && mkdir -p /app/uploads \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/api/v1/health" || exit 1

# Bootstrap baze (create_all + admin + stamp) pa uvicorn (1 worker zbog schedulera)
CMD ["bash", "scripts/start.sh"]
