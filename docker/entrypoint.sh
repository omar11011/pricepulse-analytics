#!/usr/bin/env bash
# ============================================================
# PricePulse Analytics — Docker Entrypoint
# ============================================================
# Sequence:
#   1. Wait for PostgreSQL to be ready (if using PG)
#   2. Create tables via SQLAlchemy init_db() (works for both PG and SQLite)
#   3. Run seed_data.py (idempotent — products + price history)
#   4. Launch Streamlit dashboard
# ============================================================

set -euo pipefail

# ── Configuration ────────────────────────────────────────────
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DATABASE_URL="${DATABASE_URL:-}"

MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-60}"
SEED_DATA="${SEED_DATA:-true}"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║        PricePulse Analytics — Docker Entry Point        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "DATABASE_URL: ${DATABASE_URL:-(not set, will use individual DB_* vars)}"
echo "DB_HOST:      ${DB_HOST}:${DB_PORT}"
echo "Seed data:    ${SEED_DATA}"
echo ""

# ── Step 1: Wait for database ────────────────────────────────
# Only wait if using PostgreSQL (SQLite doesn't need a server)
if [[ "${DATABASE_URL}" == postgresql* ]] || [[ -z "${DATABASE_URL}" ]]; then
    echo "⏳ Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."

    if command -v wait-for-it &> /dev/null; then
        wait-for-it "${DB_HOST}:${DB_PORT}" --timeout="${MAX_WAIT_SECONDS}" --strict -- \
            echo "✅ PostgreSQL port is open"
    else
        # Fallback: poll with Python
        echo "   (wait-for-it not found, using Python socket poll)"
        python3 -c "
import socket, sys, time
host = '${DB_HOST}'
port = ${DB_PORT}
max_wait = ${MAX_WAIT_SECONDS}
start = time.time()
while time.time() - start < max_wait:
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print(f'✅ PostgreSQL port {port} is open on {host}')
        sys.exit(0)
    except (ConnectionRefusedError, OSError):
        time.sleep(1)
print(f'❌ PostgreSQL not available after {max_wait}s')
sys.exit(1)
"
    fi

    # Give PostgreSQL a couple extra seconds to finish initialization
    sleep 2
else
    echo "✅ SQLite mode — no external database to wait for"
fi

# ── Step 2: Create tables via SQLAlchemy init_db() ───────────
echo ""
echo "📐 Creating database tables via SQLAlchemy init_db()..."

python3 -c "
from src.database.connection import init_db, check_connection, SessionFactory
from src.config import settings
from loguru import logger

dialect = settings.database.dialect_name.upper()
logger.info(f'Dialect detected: {dialect}')

if check_connection():
    init_db()
    logger.info('✅ Tables created/verified successfully')
else:
    logger.error('❌ Cannot connect to database')
    exit(1)
"

# ── Step 3: Seed data ────────────────────────────────────────
if [[ "${SEED_DATA}" == "true" ]]; then
    echo ""
    echo "🌱 Seeding database with sample data..."
    python3 -m scripts.seed_data
    echo "✅ Seed data loaded"
else
    echo ""
    echo "⏭️  Skipping seed data (SEED_DATA=${SEED_DATA})"
fi

# ── Step 4: Launch Streamlit ─────────────────────────────────
echo ""
echo "🚀 Starting Streamlit dashboard on port 8501..."
echo "   Access: http://localhost:8501"
echo ""

exec streamlit run src/dashboard/app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=true \
    --browser.gatherUsageStats=false
