# ============================================================
# PricePulse Analytics — Dockerfile
# Multi-stage build for Streamlit dashboard
# ============================================================
# Build:  docker compose build
# Run:    docker compose up
# ============================================================

# ── Stage 1: Builder — install Python dependencies ──────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy dependency files first (cache layer)
COPY requirements.txt requirements-pg.txt ./

# Install Python deps into a clean prefix
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    -r requirements-pg.txt

# ── Stage 2: Runtime — slim image with app code ─────────────
FROM python:3.12-slim

LABEL maintainer="PricePulse Analytics"
LABEL description="Dashboard de análisis de precios tecnológicos — Streamlit + PostgreSQL"

# System packages needed by Playwright (for future scraping)
# and psycopg2 (libpq5 for client libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libpq5 \
    wait-for-it \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Set working directory
WORKDIR /app

# Copy application code
COPY src/              ./src/
COPY scripts/          ./scripts/
COPY sql/              ./sql/
COPY .streamlit/       ./.streamlit/
COPY requirements.txt  requirements-pg.txt ./

# Copy entrypoint script
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create data directory for SQLite (fallback mode)
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose Streamlit port
EXPOSE 8501

# Health check — verify Streamlit is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Entry point: wait for DB → init tables → seed data → launch Streamlit
ENTRYPOINT ["/app/entrypoint.sh"]
