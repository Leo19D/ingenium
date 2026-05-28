# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage: base — common system deps
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for: PDF parsing (poppler), OCR fallback (tesseract),
# WeasyPrint (cairo, pango), camelot (ghostscript), psql client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libpq-dev \
    poppler-utils \
    ghostscript \
    libgl1 \
    libglib2.0-0 \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-liberation \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hrv \
    tesseract-ocr-deu \
    tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# =============================================================================
# Stage: dev — with dev deps, hot reload, mounted source
# =============================================================================
FROM base AS dev

COPY pyproject.toml /app/
RUN pip install -e ".[dev]"

# Source is mounted via docker-compose volume in dev
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# =============================================================================
# Stage: prod — slim image, no dev deps, no source modifications
# =============================================================================
FROM base AS prod

COPY pyproject.toml /app/
RUN pip install .

COPY ./app /app/app
COPY ./alembic /app/alembic
COPY ./alembic.ini /app/

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
