#!/usr/bin/env bash
# =============================================================================
# install-local.sh — ownedpulse dev (local) install
#
# Rebuilds ownedpulse-api and ownedpulse-ui from source and starts them against
# external ai-stack services (postgres, qdrant, ollama, docling, langfuse).
#
# Prerequisites:
#   - External ai-stack services MUST be running and accessible.
#   - docker + docker compose (v2) must be installed.
#   - This script expects docker-compose.override.yml to exist (it wires
#     api/ui to the external ai-stack network and hardcodes connection vars).
#
# What this script does NOT touch:
#   - No PostgreSQL / Qdrant / Ollama / Docling / Langfuse containers
#   - No volumes or persistent data
#   - No external infrastructure
#
# Usage:
#   ./install-local.sh              # build + start
#   ./install-local.sh --no-build   # restart without rebuilding images
#   ./install-local.sh --stop       # stop api + ui only
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colour helpers ─────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # no colour

log()  { echo -e "${GREEN}[install-local]${NC} $*"; }
warn() { echo -e "${YELLOW}[install-local]${NC} $*"; }
err()  { echo -e "${RED}[install-local]${NC} $*" >&2; }

# ── Parse arguments ────────────────────────────────────────────────────
BUILD=true
STOP_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --no-build) BUILD=false ;;
        --stop)     STOP_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--no-build] [--stop]"
            exit 0
            ;;
        *) err "Unknown argument: $arg"; exit 1 ;;
    esac
done

# ── Prerequisites ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    err "docker is not installed or not in PATH"
    exit 1
fi

if ! docker compose version &>/dev/null; then
    err "docker compose (v2) is required"
    exit 1
fi

if [ ! -f docker-compose.override.yml ]; then
    err "docker-compose.override.yml not found — this script requires the dev override"
    exit 1
fi

# ── Stop only ──────────────────────────────────────────────────────────
if [ "$STOP_ONLY" = true ]; then
    log "Stopping ownedpulse-api and ownedpulse-ui..."
    docker compose stop ownedpulse-api ownedpulse-ui
    log "Done. External services are untouched."
    exit 0
fi

# ── Ensure data directories exist ──────────────────────────────────────
mkdir -p data/api data/regulatory_archive

# ── Build images ───────────────────────────────────────────────────────
if [ "$BUILD" = true ]; then
    log "Building ownedpulse-api image..."
    docker compose build ownedpulse-api

    log "Building ownedpulse-ui image..."
    docker compose build ownedpulse-ui
else
    log "Skipping build (--no-build)."
fi

# ── Restart api + ui ───────────────────────────────────────────────────
log "Stopping existing api/ui containers (if any)..."
docker compose stop ownedpulse-api ownedpulse-ui 2>/dev/null || true
docker compose rm -f ownedpulse-api ownedpulse-ui 2>/dev/null || true

log "Starting ownedpulse-api and ownedpulse-ui..."
docker compose up -d ownedpulse-api ownedpulse-ui

# ── Wait for healthy ───────────────────────────────────────────────────
log "Waiting for ownedpulse-api to become healthy..."
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' ownedpulse-api 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        log "ownedpulse-api is healthy."
        break
    fi
    if [ "$i" -eq 30 ]; then
        warn "ownedpulse-api did not become healthy within 30s. Check: docker logs ownedpulse-api"
    fi
    sleep 1
done

log "--------------------------------------------------"
log "ownedpulse local dev install complete."
log "  API  → http://localhost:8001"
log "  UI   → http://localhost:5173"
log "  Health → http://localhost:8001/api/health"
log ""
log "To stop:  ./install-local.sh --stop"
log "To rebuild and restart: ./install-local.sh"
log "To restart without rebuild: ./install-local.sh --no-build"
log "--------------------------------------------------"
