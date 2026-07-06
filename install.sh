#!/bin/bash
# ownedpulse install.sh
# Single entry point for both full install (all bundled) and dev install
# (external services). Idempotent — safe to re-run on an existing installation.
#
# Usage:
#   ./install.sh              # build images + start all bundled services
#   ./install.sh --no-build   # skip image build (dev, images already built)
#   ./install.sh --stop       # stop only ownedpulse-api + ownedpulse-ui
#
# Each service defaults to bundled mode. Set *_MODE=external in .env to use
# an existing service (the matching *_HOST / *_PORT / credential vars must
# also be set). See .env.example for all vars.
#
# Requires: docker, docker compose v2 plugin, .env file,
#           NVIDIA GPU with nvidia-container-toolkit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── helpers ──────────────────────────────────────────────────────────────

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

# ── args ─────────────────────────────────────────────────────────────────

BUILD=true
STOP_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=false ;;
    --stop)     STOP_ONLY=true ;;
    --help|-h)
      echo "Usage: $0 [--no-build] [--stop]"
      echo ""
      echo "  (none)        Full install — build images, start services, run migrations, pull models"
      echo "  --no-build    Skip image build (dev mode — images already built)"
      echo "  --stop        Stop ownedpulse-api and ownedpulse-ui only"
      exit 0
      ;;
    *) die "Unknown argument: $arg" ;;
  esac
done

# ── Step 0 — Load .env ───────────────────────────────────────────────────

ENV_FILE="$SCRIPT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  die ".env file not found at $SCRIPT_DIR/.env\nCopy .env.example to .env and fill in your values."
fi
set -a; source "$ENV_FILE"; set +a

# ── defaults for vars not in .env ────────────────────────────────────────

POSTGRES_MODE="${POSTGRES_MODE:-bundled}"
QDRANT_MODE="${QDRANT_MODE:-bundled}"
OLLAMA_MODE="${OLLAMA_MODE:-bundled}"
DOCLING_MODE="${DOCLING_MODE:-bundled}"
LANGFUSE_MODE="${LANGFUSE_MODE:-bundled}"

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-knowledge_base}"
POSTGRES_HOST="${POSTGRES_HOST:-ownedpulse-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

QDRANT_HOST="${QDRANT_HOST:-ownedpulse-qdrant}"
QDRANT_PORT="${QDRANT_PORT:-6333}"

OLLAMA_HOST="${OLLAMA_HOST:-http://ownedpulse-ollama:11434}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

DOCLING_HOST="${DOCLING_HOST:-http://ownedpulse-docling:5001}"

LANGFUSE_HOST="${LANGFUSE_HOST:-http://ownedpulse-langfuse:3000}"
LANGFUSE_URL="${LANGFUSE_URL:-http://localhost:${LANGFUSE_PORT:-3001}}"

API_PORT="${API_PORT:-8001}"
UI_PORT="${UI_PORT:-5173}"

LLM_MODEL="${OLLAMA_GEN_MODEL:-phi4:14b-q8_0}"
EMBED_MODEL="${OLLAMA_EMBED_MODEL:-mxbai-embed-large}"

# ── stop-only mode ───────────────────────────────────────────────────────

if [[ "$STOP_ONLY" == true ]]; then
  log_info "Stopping ownedpulse-api and ownedpulse-ui..."
  docker compose stop ownedpulse-api ownedpulse-ui 2>/dev/null || true
  log_ok "Stopped. Infrastructure services are untouched."
  exit 0
fi

# ── Step 1 — Preflight ───────────────────────────────────────────────────

log_section "Step 1: Preflight"

docker info > /dev/null 2>&1 || die "Docker is not running. Start Docker and retry."
log_ok "Docker is running"

docker compose version > /dev/null 2>&1 || die "docker compose (v2) not found. Install Docker Compose v2 plugin."
log_ok "docker compose available"

if [[ "${POSTGRES_PASSWORD:-}" == "change_me" ]] || [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  die "POSTGRES_PASSWORD is not set or is still 'change_me'. Set a real password in .env"
fi
log_ok "POSTGRES_PASSWORD is set"

# OLLAMA / DOCLING GPU checks — only needed if those services are bundled
NEED_GPU=false
[[ "${OLLAMA_MODE}" == "bundled" ]] && NEED_GPU=true
[[ "${DOCLING_MODE}" == "bundled" ]] && NEED_GPU=true

if [[ "$NEED_GPU" == true ]]; then
  nvidia-smi > /dev/null 2>&1 || die "No NVIDIA GPU detected (nvidia-smi failed).\nOllama/Docling require an NVIDIA GPU with drivers and nvidia-container-toolkit."
  log_ok "NVIDIA GPU detected"

  log_info "Checking nvidia-container-toolkit..."
  if dpkg -l nvidia-container-toolkit 2>/dev/null | grep -q '^ii'; then
    log_ok "nvidia-container-toolkit installed"
  else
    log_warn "nvidia-container-toolkit package not found. If GPU containers fail:\n  sudo apt install -y nvidia-container-toolkit && sudo systemctl restart docker"
  fi
else
  log_warn "Ollama and Docling both external — skipping GPU check"
fi

# Required env vars for Langfuse (only if bundled)
if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  for var in LANGFUSE_NEXTAUTH_SECRET LANGFUSE_SALT LANGFUSE_INIT_USER_EMAIL LANGFUSE_INIT_USER_PASSWORD LANGFUSE_DB_PASSWORD; do
    if [[ -z "${!var:-}" ]] || [[ "${!var}" == *"generate_with"* ]] || [[ "${!var}" == *"change_me"* ]]; then
      die "Required variable $var is not set in .env (needed for bundled Langfuse)"
    fi
  done
  log_ok "Langfuse env vars present"
fi

# ── Step 2 — Langfuse API keys ───────────────────────────────────────────

if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
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
  if [[ "$NEED_RELOAD" == true ]]; then
    set -a; source "$ENV_FILE"; set +a
    log_warn "Langfuse API keys generated and saved to .env"
  fi
fi

# ── Step 3 — Start infrastructure ────────────────────────────────────────

log_section "Step 3: Infrastructure services"

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
    log_info "Using external $svc"
  fi
done

if [[ ${#PROFILES[@]} -gt 0 ]]; then
  docker compose "${PROFILES[@]}" up -d "${INFRA_SERVICES[@]}" 2>&1 \
    || die "docker compose up failed for infrastructure services. Check output above."
  log_ok "Infrastructure started"
fi

# ── Step 4 — Langfuse database ───────────────────────────────────────────

if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  log_section "Step 4: Langfuse database"

  LANGFUSE_DB_USER="${LANGFUSE_DB_USER:-langfuse}"
  LANGFUSE_DB_NAME="${LANGFUSE_DB_NAME:-langfuse}"
  LANGFUSE_DB_PASSWORD="${LANGFUSE_DB_PASSWORD:-}"
  PG_HOST="${POSTGRES_HOST}"

  log_info "Waiting for PostgreSQL..."
  waited=0
  if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
    while ! docker exec "$PG_HOST" pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; do
      (( waited >= 60 )) && die "PostgreSQL did not become healthy within 60s.\nCheck: docker logs $PG_HOST 2>&1 | tail -30"
      sleep 2; waited=$((waited + 2)); echo -n "."
    done
  else
    while ! docker run --rm postgres:16 pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" > /dev/null 2>&1; do
      (( waited >= 60 )) && die "External PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT} did not become healthy within 60s."
      sleep 2; waited=$((waited + 2)); echo -n "."
    done
  fi
  echo ""; log_ok "PostgreSQL is ready"

  create_langfuse_db() {
    if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
      local EXEC="docker exec $PG_HOST psql -U $POSTGRES_USER"
      local user_exists; user_exists=$(docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_roles WHERE rolname='${LANGFUSE_DB_USER}'" 2>/dev/null || true)
      if [[ "$user_exists" != "1" ]]; then
        log_info "Creating user: $LANGFUSE_DB_USER"
        docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -c "CREATE USER \"${LANGFUSE_DB_USER}\" WITH PASSWORD '${LANGFUSE_DB_PASSWORD}';" 2>&1 || die "Failed to create Langfuse database user"
      fi
      local db_exists; db_exists=$(docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='${LANGFUSE_DB_NAME}'" 2>/dev/null || true)
      if [[ "$db_exists" != "1" ]]; then
        log_info "Creating database: $LANGFUSE_DB_NAME"
        docker exec "$PG_HOST" psql -U "$POSTGRES_USER" -c "CREATE DATABASE \"${LANGFUSE_DB_NAME}\" OWNER \"${LANGFUSE_DB_USER}\";" 2>&1 || die "Failed to create Langfuse database"
      fi
    else
      local PSQL="docker run --rm postgres:16 psql postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres"
      $PSQL -tAc "SELECT 1 FROM pg_roles WHERE rolname='${LANGFUSE_DB_USER}'" 2>/dev/null | grep -q 1 || {
        log_info "Creating user: $LANGFUSE_DB_USER"
        $PSQL -c "CREATE USER \"${LANGFUSE_DB_USER}\" WITH PASSWORD '${LANGFUSE_DB_PASSWORD}';" 2>&1 || die "Failed to create Langfuse database user on external postgres"
      }
      $PSQL -tAc "SELECT 1 FROM pg_database WHERE datname='${LANGFUSE_DB_NAME}'" 2>/dev/null | grep -q 1 || {
        log_info "Creating database: $LANGFUSE_DB_NAME"
        $PSQL -c "CREATE DATABASE \"${LANGFUSE_DB_NAME}\" OWNER \"${LANGFUSE_DB_USER}\";" 2>&1 || die "Failed to create Langfuse database on external postgres"
      }
    fi
    log_ok "Langfuse database ready"
  }
  create_langfuse_db

  log_info "Starting Langfuse..."
  docker compose --profile langfuse up -d langfuse 2>&1 || die "docker compose up failed for langfuse."
  log_ok "Langfuse started"
fi

# ── Step 5 — Health checks ───────────────────────────────────────────────

log_section "Step 5: Health checks"

wait_for() {
  local label="$1" cmd="$2" timeout="${3:-60}"
  local elapsed=0 interval=5
  log_info "Waiting for $label..."
  while ! eval "$cmd" > /dev/null 2>&1; do
    (( elapsed >= timeout )) && die "$label did not become healthy within ${timeout}s."
    sleep "$interval"; elapsed=$(( elapsed + interval )); echo -n "."
  done
  echo ""; log_ok "$label is healthy"
}

if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
  wait_for "postgres" "docker exec ownedpulse-postgres pg_isready -U $POSTGRES_USER" 60
else
  wait_for "postgres (external)" "docker run --rm postgres:16 pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER" 60
fi

if [[ "${QDRANT_MODE}" == "bundled" ]]; then
  wait_for "qdrant" "docker exec ownedpulse-qdrant wget -qO- http://localhost:6333/healthz" 60
else
  wait_for "qdrant (external)" "curl -sf http://${QDRANT_HOST}:${QDRANT_PORT}/healthz" 60
fi

if [[ "${OLLAMA_MODE}" == "bundled" ]]; then
  wait_for "ollama" "curl -sf http://localhost:${OLLAMA_PORT}/api/tags" 120
else
  wait_for "ollama (external)" "curl -sf ${OLLAMA_HOST}/api/tags" 120
fi

if [[ "${DOCLING_MODE}" == "bundled" ]]; then
  wait_for "docling" "docker exec ownedpulse-docling curl -sf http://localhost:5001/health" 180
else
  wait_for "docling (external)" "curl -sf ${DOCLING_HOST}/health" 180
fi

if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  wait_for "langfuse" "docker exec ownedpulse-langfuse wget -qO- http://localhost:3000/api/public/health" 60
else
  wait_for "langfuse (external)" "curl -sf ${LANGFUSE_HOST}/api/public/health" 60
fi

# ── Step 6 — Migrations ──────────────────────────────────────────────────

log_section "Step 6: Database migrations"

apply_migration() {
  local file="$1"
  log_info "Applying: $(basename "$file")"
  local rc=0
  if [[ "${POSTGRES_MODE}" == "bundled" ]]; then
    docker exec -i ownedpulse-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < "$file" 2>&1 || rc=$?
  else
    docker run --rm -i postgres:16 psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}" -v ON_ERROR_STOP=1 < "$file" 2>&1 || rc=$?
  fi
  (( rc != 0 )) && die "Migration failed: $(basename "$file") (exit $rc)"
  log_ok "Migration applied: $(basename "$file")"
}

MIGRATIONS=(
  "api/migrations/000_base_schema.sql"
  "api/migrations/001_ingestion_trace.up.sql"
  "api/migrations/002_status_skipped.up.sql"
  "api/migrations/003_not_viable_recheck.up.sql"
  "api/migrations/004_not_viable_status.up.sql"
  "api/migrations/005_chunks_table.up.sql"
  "api/migrations/006_ingestion_doc_doc_id_unique.up.sql"
  "scripts/migrations/migrate_feed_config.sql"
)

for migration in "${MIGRATIONS[@]}"; do
  [[ ! -f "$SCRIPT_DIR/$migration" ]] && die "Migration file not found: $migration"
  apply_migration "$SCRIPT_DIR/$migration"
done

# ── Step 7 — Ollama models ───────────────────────────────────────────────

if [[ "${OLLAMA_MODE}" == "bundled" ]]; then
  log_section "Step 7: Ollama models"

  pull_model() {
    local model="$1" hint="$2"
    local present; present=$(docker exec ownedpulse-ollama ollama list 2>/dev/null | grep -c "^${model}" || true)
    if [[ "$present" -gt 0 ]]; then
      log_ok "Model already available: $model"
      return
    fi
    log_info "Pulling $model (~${hint}) — this may take several minutes..."
    docker exec ownedpulse-ollama ollama pull "$model" || die "Failed to pull model: $model"
    log_ok "Model pulled: $model"
  }

  pull_model "$LLM_MODEL" "9 GB"
  pull_model "$EMBED_MODEL" "670 MB"
else
  log_info "Using external Ollama — skipping model pull"
fi

# ── Step 8 — Build + start OwnedPulse ────────────────────────────────────

log_section "Step 8: Starting OwnedPulse"

if [[ "$BUILD" == true ]]; then
  log_info "Building ownedpulse-api..."
  docker compose build ownedpulse-api 2>&1 || die "Failed to build ownedpulse-api"
  log_info "Building ownedpulse-ui..."
  docker compose build ownedpulse-ui 2>&1 || die "Failed to build ownedpulse-ui"
fi

docker compose up -d ownedpulse-api ownedpulse-ui 2>&1 \
  || die "Failed to start ownedpulse-api or ownedpulse-ui."

wait_for "ownedpulse-api" "curl -sf http://localhost:${API_PORT}/health" 60

# ── Step 9 — Summary ─────────────────────────────────────────────────────

log_section "Installation Complete"
echo ""
echo "  Services:"
printf "  %-12s %s  →  %s\n" "postgres"  "[${POSTGRES_MODE}]"  "${POSTGRES_HOST}:${POSTGRES_PORT}"
printf "  %-12s %s  →  %s\n" "qdrant"    "[${QDRANT_MODE}]"    "${QDRANT_HOST}:${QDRANT_PORT}"
printf "  %-12s %s  →  %s\n" "ollama"    "[${OLLAMA_MODE}]"    "${OLLAMA_HOST}"
printf "  %-12s %s  →  %s\n" "docling"   "[${DOCLING_MODE}]"   "${DOCLING_HOST}"
printf "  %-12s %s  →  %s\n" "langfuse"  "[${LANGFUSE_MODE}]"  "${LANGFUSE_URL}"
echo ""
echo "  OwnedPulse UI:  http://localhost:${UI_PORT}"
echo "  OwnedPulse API: http://localhost:${API_PORT}"
echo ""
echo "  Next steps:"
echo "  1. Open the UI at http://localhost:${UI_PORT}"
echo "  2. Use the Initial Load button to populate the corpus"
if [[ "${LANGFUSE_MODE}" == "bundled" ]]; then
  echo "  3. Log into Langfuse at ${LANGFUSE_URL}"
  echo "     Email:    ${LANGFUSE_INIT_USER_EMAIL}"
  echo "     Password: (as set in .env)"
fi
echo ""
