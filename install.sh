#!/bin/bash
# regpulse install.sh
# Idempotent — safe to re-run on an existing installation.
# Requires: docker, docker compose plugin, .env in working directory,
#           NVIDIA GPU with nvidia-container-toolkit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Logging helpers ────────────────────────────────────────────────────

log_info()    { echo "[•] $*"; }
log_ok()      { echo "[✓] $*"; }
log_warn()    { echo "[!] $*"; }
log_error()   { echo "[✗] $*" >&2; }
log_section() { echo ""; echo "══════════════════════════════════════"; echo "  $*"; echo "══════════════════════════════════════"; }

die() {
  log_error "$*"
  echo ""
  echo "Installation failed. Fix the error above and re-run install.sh"
  echo "All changes are safe to re-run — install.sh is idempotent."
  exit 1
}

# ── Step 0 — Load configuration ───────────────────────────────────────

ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  die ".env file not found at $SCRIPT_DIR/.env\nCopy .env.example to .env and fill in your values."
fi

set -a
source "$ENV_FILE"
set +a

# ── Step 1 — Preflight checks ─────────────────────────────────────────

log_section "Step 1: Preflight checks"

docker info > /dev/null 2>&1 || die "Docker is not running. Start Docker and retry."
log_ok "Docker is running"

docker compose version > /dev/null 2>&1 || die "docker compose (v2) not found. Install Docker Compose v2 plugin."
log_ok "docker compose available"

if [[ "${POSTGRES_PASSWORD:-}" == "change_me" ]] || [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  die "POSTGRES_PASSWORD is not set or is still 'change_me'. Set a real password in .env"
fi
log_ok "POSTGRES_PASSWORD is set"

nvidia-smi > /dev/null 2>&1 || die "No NVIDIA GPU detected (nvidia-smi failed). RegPulse requires an NVIDIA GPU with drivers and nvidia-container-toolkit installed."
log_ok "NVIDIA GPU detected"

log_info "Verifying GPU access from Docker..."
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1 \
  || die "nvidia-container-toolkit is not configured correctly.\nRun: sudo apt install nvidia-container-toolkit && sudo systemctl restart docker"
log_ok "nvidia-container-toolkit working"

# Required env vars
for var in POSTGRES_PASSWORD LANGFUSE_NEXTAUTH_SECRET LANGFUSE_SALT LANGFUSE_INIT_USER_EMAIL LANGFUSE_INIT_USER_PASSWORD; do
  if [[ -z "${!var:-}" ]] || [[ "${!var}" == *"generate_with"* ]] || [[ "${!var}" == *"change_me"* ]]; then
    if [[ "$var" == "POSTGRES_PASSWORD" ]]; then
      die "POSTGRES_PASSWORD is not set or is still 'change_me'. Set a real password in .env"
    else
      die "Required variable $var is not set in .env"
    fi
  fi
done
log_ok "Required env vars present"

# ── Step 2 — Prepare Langfuse API keys ────────────────────────────────

log_section "Step 2: Langfuse API keys"

NEED_RELOAD=false

if [[ -z "${LANGFUSE_PUBLIC_KEY:-}" ]]; then
  LANGFUSE_PUBLIC_KEY="pk-lf-$(openssl rand -hex 16)"
  sed -i "s|^LANGFUSE_PUBLIC_KEY=.*|LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY|" "$ENV_FILE"
  NEED_RELOAD=true
  log_ok "Generated LANGFUSE_PUBLIC_KEY"
else
  log_ok "LANGFUSE_PUBLIC_KEY already set"
fi

if [[ -z "${LANGFUSE_SECRET_KEY:-}" ]]; then
  LANGFUSE_SECRET_KEY="sk-lf-$(openssl rand -hex 16)"
  sed -i "s|^LANGFUSE_SECRET_KEY=.*|LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY|" "$ENV_FILE"
  NEED_RELOAD=true
  log_ok "Generated LANGFUSE_SECRET_KEY"
else
  log_ok "LANGFUSE_SECRET_KEY already set"
fi

if [[ "$NEED_RELOAD" == "true" ]]; then
  set -a; source "$ENV_FILE"; set +a
  log_warn "Langfuse API keys have been generated and saved to .env"
fi

# ── Step 3 — Start bundled infrastructure ─────────────────────────────

log_section "Step 3: Starting infrastructure"

POSTGRES_MODE="${POSTGRES_MODE:-bundled}"
QDRANT_MODE="${QDRANT_MODE:-bundled}"
OLLAMA_MODE="${OLLAMA_MODE:-bundled}"
DOCLING_MODE="${DOCLING_MODE:-bundled}"
LANGFUSE_MODE="${LANGFUSE_MODE:-bundled}"

PROFILES=()
INFRA_SERVICES=()

for svc in postgres qdrant ollama docling; do
  MODE_VAR="${svc^^}_MODE"
  MODE="${!MODE_VAR:-bundled}"
  if [[ "$MODE" == "bundled" ]]; then
    PROFILES+=(--profile "$svc")
    INFRA_SERVICES+=("$svc")
    log_info "Starting bundled $svc..."
  else
    log_warn "Using external $svc — skipping container start"
  fi
done

if [[ ${#PROFILES[@]} -gt 0 ]]; then
  docker compose "${PROFILES[@]}" up -d "${INFRA_SERVICES[@]}" 2>&1 \
    || die "docker compose up failed for infrastructure services. Check output above."
  log_ok "Infrastructure containers started"
fi

# ── Step 4 — Prepare Langfuse database ────────────────────────────────

log_section "Step 4: Langfuse database"

LANGFUSE_DB_USER="${LANGFUSE_DB_USER:-langfuse}"
LANGFUSE_DB_NAME="${LANGFUSE_DB_NAME:-langfuse}"
LANGFUSE_DB_PASSWORD="${LANGFUSE_DB_PASSWORD:-}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-knowledge_base}"
POSTGRES_HOST="${POSTGRES_HOST:-regpulse-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# Wait for postgres first
log_info "Waiting for PostgreSQL before creating Langfuse database..."
if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
  waited=0
  while ! docker exec regpulse-postgres pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; do
    if (( waited >= 60 )); then
      die "PostgreSQL did not become healthy within 60s.\nCheck logs: docker logs regpulse-postgres 2>&1 | tail -30"
    fi
    sleep 2
    waited=$((waited + 2))
    echo -n "."
  done
  echo ""
  log_ok "PostgreSQL is ready"
else
  waited=0
  while ! docker run --rm postgres:16 pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" > /dev/null 2>&1; do
    if (( waited >= 60 )); then
      die "External PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT} did not become healthy within 60s."
    fi
    sleep 2
    waited=$((waited + 2))
    echo -n "."
  done
  echo ""
  log_ok "External PostgreSQL is ready"
fi

# Create Langfuse user and database
create_langfuse_db() {
  if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
    local PG_HOST="regpulse-postgres"
    local EXEC="docker exec $PG_HOST"
  else
    local EXEC="docker run --rm postgres:16"
  fi

  # Create user if not exists
  if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
    local user_exists
    user_exists=$(docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -tAc \
      "SELECT 1 FROM pg_roles WHERE rolname='${LANGFUSE_DB_USER}'" 2>/dev/null || true)
    if [[ "$user_exists" != "1" ]]; then
      log_info "Creating user: $LANGFUSE_DB_USER"
      docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -c \
        "CREATE USER \"${LANGFUSE_DB_USER}\" WITH PASSWORD '${LANGFUSE_DB_PASSWORD}';" 2>&1 \
        || die "Failed to create Langfuse database user"
      log_ok "Langfuse user created"
    else
      log_ok "Langfuse user already exists"
    fi

    # Create database if not exists
    local db_exists
    db_exists=$(docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -tAc \
      "SELECT 1 FROM pg_database WHERE datname='${LANGFUSE_DB_NAME}'" 2>/dev/null || true)
    if [[ "$db_exists" != "1" ]]; then
      log_info "Creating database: $LANGFUSE_DB_NAME"
      docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -c \
        "CREATE DATABASE \"${LANGFUSE_DB_NAME}\" OWNER \"${LANGFUSE_DB_USER}\";" 2>&1 \
        || die "Failed to create Langfuse database"
      log_ok "Langfuse database created"
    else
      log_ok "Langfuse database already exists"
    fi
  else
    local PSQL_OPTS="-h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER"
    docker run --rm postgres:16 psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres" -tAc \
      "SELECT 1 FROM pg_roles WHERE rolname='${LANGFUSE_DB_USER}'" 2>/dev/null | grep -q 1 || {
      log_info "Creating user: $LANGFUSE_DB_USER"
      docker run --rm postgres:16 psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres" -c \
        "CREATE USER \"${LANGFUSE_DB_USER}\" WITH PASSWORD '${LANGFUSE_DB_PASSWORD}';" 2>&1 \
        || die "Failed to create Langfuse database user on external postgres"
      log_ok "Langfuse user created"
    }

    docker run --rm postgres:16 psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres" -tAc \
      "SELECT 1 FROM pg_database WHERE datname='${LANGFUSE_DB_NAME}'" 2>/dev/null | grep -q 1 || {
      log_info "Creating database: $LANGFUSE_DB_NAME"
      docker run --rm postgres:16 psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres" -c \
        "CREATE DATABASE \"${LANGFUSE_DB_NAME}\" OWNER \"${LANGFUSE_DB_USER}\";" 2>&1 \
        || die "Failed to create Langfuse database on external postgres"
      log_ok "Langfuse database created"
    }
  fi

  log_ok "Langfuse database ready"
}

create_langfuse_db

# Start Langfuse after DB is ready
if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  log_info "Starting Langfuse..."
  docker compose --profile langfuse up -d langfuse 2>&1 \
    || die "docker compose up failed for langfuse. Check output above."
  log_ok "Langfuse started"
else
  log_warn "Using external Langfuse — skipping container start"
fi

# ── Step 5 — Wait for all services healthy ────────────────────────────

log_section "Step 5: Health checks"

wait_for_service() {
  local name="$1"
  local check_cmd="$2"
  local timeout="${3:-60}"
  local interval=5
  local elapsed=0

  log_info "Waiting for $name..."
  while ! eval "$check_cmd" > /dev/null 2>&1; do
    if (( elapsed >= timeout )); then
      die "$name did not become healthy within ${timeout}s.\n  Check logs: docker logs regpulse-${name,,} 2>&1 | tail -30"
    fi
    sleep "$interval"
    elapsed=$(( elapsed + interval ))
    echo -n "."
  done
  echo ""
  log_ok "$name is healthy"
}

# postgres
if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
  wait_for_service "postgres" "docker exec regpulse-postgres pg_isready -U $POSTGRES_USER" 60
else
  wait_for_service "postgres (external)" "docker run --rm postgres:16 pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER" 60
fi

# qdrant
if [[ "${QDRANT_MODE}" == "bundled" ]]; then
  wait_for_service "qdrant" "docker exec regpulse-qdrant wget -qO- http://localhost:6333/healthz" 60
else
  QDRANT_HOST="${QDRANT_HOST:-regpulse-qdrant}"
  QDRANT_PORT="${QDRANT_PORT:-6333}"
  wait_for_service "qdrant (external)" "curl -sf http://${QDRANT_HOST}:${QDRANT_PORT}/healthz" 60
fi

# ollama
if [[ "${OLLAMA_MODE}" == "bundled" ]]; then
  wait_for_service "ollama" "curl -sf http://localhost:${OLLAMA_PORT:-11434}/api/tags" 120
else
  OLLAMA_HOST="${OLLAMA_HOST:-http://regpulse-ollama:11434}"
  wait_for_service "ollama (external)" "curl -sf ${OLLAMA_HOST}/api/tags" 120
fi

# docling
if [[ "${DOCLING_MODE}" == "bundled" ]]; then
  wait_for_service "docling" "docker exec regpulse-docling curl -sf http://localhost:5001/health" 180
else
  DOCLING_HOST="${DOCLING_HOST:-http://regpulse-docling:5001}"
  wait_for_service "docling (external)" "curl -sf ${DOCLING_HOST}/health" 180
fi

# langfuse
if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  wait_for_service "langfuse" "docker exec regpulse-langfuse wget -qO- http://localhost:3000/api/public/health" 60
else
  LANGFUSE_HOST="${LANGFUSE_HOST:-http://regpulse-langfuse:3000}"
  wait_for_service "langfuse (external)" "curl -sf ${LANGFUSE_HOST}/api/public/health" 60
fi

# ── Step 6 — Apply PostgreSQL migrations ──────────────────────────────

log_section "Step 6: Database migrations"

apply_migration() {
  local file="$1"
  local filename
  filename=$(basename "$file")

  log_info "Applying migration: $filename"

  local exit_code=0
  if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
    docker exec -i regpulse-postgres \
      psql -U "${POSTGRES_USER}" \
           -d "${POSTGRES_DB}" \
           -v ON_ERROR_STOP=1 \
      < "$file" 2>&1 || exit_code=$?
  else
    docker run --rm -i postgres:16 \
      psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}" \
      -v ON_ERROR_STOP=1 \
      < "$file" 2>&1 || exit_code=$?
  fi

  if [[ $exit_code -ne 0 ]]; then
    die "Migration failed: $filename (exit code $exit_code)\nCheck the SQL file and your database state."
  fi
  log_ok "Migration applied: $filename"
}

MIGRATIONS=(
  "api/migrations/000_base_schema.sql"
  "api/migrations/001_ingestion_trace.up.sql"
  "api/migrations/002_status_skipped.up.sql"
  "api/migrations/003_not_viable_recheck.up.sql"
  "api/migrations/004_not_viable_status.up.sql"
  "scripts/migrations/migrate_feed_config.sql"
)

for migration in "${MIGRATIONS[@]}"; do
  if [[ ! -f "$SCRIPT_DIR/$migration" ]]; then
    die "Migration file not found: $migration"
  fi
  apply_migration "$SCRIPT_DIR/$migration"
done

# ── Step 7 — Pull Ollama models ───────────────────────────────────────

log_section "Step 7: Ollama models"

LLM_MODEL="${LLM_MODEL:-phi4:14b-q8_0}"
EMBED_MODEL="${EMBED_MODEL:-mxbai-embed-large}"

pull_model() {
  local model="$1"
  local size_hint="$2"

  if [[ "${OLLAMA_MODE:-bundled}" == "bundled" ]]; then
    local present
    present=$(docker exec regpulse-ollama ollama list 2>/dev/null | grep -c "^${model}" || true)
  else
    local present
    present=$(curl -sf "${OLLAMA_HOST}/api/tags" 2>/dev/null | grep -c "\"${model}\"" || true)
  fi

  if [[ "$present" -gt 0 ]]; then
    log_ok "Model already available: $model"
    return
  fi

  log_info "Pulling model: $model (~${size_hint}) — this may take several minutes..."
  log_warn "Do not interrupt this process."

  if [[ "${OLLAMA_MODE:-bundled}" == "bundled" ]]; then
    docker exec regpulse-ollama ollama pull "$model" || die "Failed to pull model: $model\nCheck Ollama logs: docker logs regpulse-ollama 2>&1 | tail -30"
  else
    curl -sf -X POST "${OLLAMA_HOST}/api/pull" -d "{\"name\":\"${model}\"}" \
      || die "Failed to pull model: $model\nCheck external Ollama server at ${OLLAMA_HOST}"
  fi
  log_ok "Model pulled: $model"
}

pull_model "$LLM_MODEL" "9 GB"
pull_model "$EMBED_MODEL" "670 MB"

# ── Step 8 — Start regpulse-api and regpulse-ui ───────────────────────

log_section "Step 8: Starting RegPulse"

docker compose up -d regpulse-api regpulse-ui 2>&1 \
  || die "Failed to start regpulse-api or regpulse-ui. Check: docker compose logs"

wait_for_service "regpulse-api" "curl -sf http://localhost:${API_PORT:-8001}/health" 60

# ── Step 9 — Final summary ────────────────────────────────────────────

log_section "Installation Complete"
echo ""
echo "  Services:"
for svc in postgres qdrant ollama docling langfuse; do
  MODE_VAR="${svc^^}_MODE"
  MODE="${!MODE_VAR:-bundled}"
  printf "  %-12s %s\n" "$svc" "[$MODE]"
done
echo ""
echo "  RegPulse UI:  http://localhost:${UI_PORT:-5173}"
echo "  RegPulse API: http://localhost:${API_PORT:-8001}"
echo "  Langfuse:     ${LANGFUSE_URL:-http://localhost:${LANGFUSE_PORT:-3001}}"
echo ""
echo "  Next steps:"
echo "  1. Open the UI at http://localhost:${UI_PORT:-5173}"
echo "  2. Use the Initial Load button to populate the corpus"
echo "  3. Log into Langfuse at ${LANGFUSE_URL:-http://localhost:${LANGFUSE_PORT:-3001}}"
echo "     Email:    ${LANGFUSE_INIT_USER_EMAIL}"
echo "     Password: (as set in .env)"
echo ""
