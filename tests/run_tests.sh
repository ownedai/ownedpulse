#!/bin/bash
# ownedpulse test runner v2
# Usage:
#   bash tests/run_tests.sh           — run all suites
#   bash tests/run_tests.sh api       — API endpoint tests only
#   bash tests/run_tests.sh integ     — integration / routing tests only
#   bash tests/run_tests.sh comply    — compliance / Annex 11 tests only
#   bash tests/run_tests.sh e2e       — E2E Playwright UI tests only
#   bash tests/run_tests.sh fast      — api + comply only (no LLM, ~30s)
#   bash tests/run_tests.sh fields    — field name correctness tests only

set -euo pipefail

API_URL="${OWNEDPULSE_API_URL:-http://localhost:8001}"
PG_DSN="${OWNEDPULSE_PG_DSN:-host=localhost port=5432 dbname=knowledge_base user=postgres password=${POSTGRES_PASSWORD:-}}"
SUITE="${1:-all}"
PASS=0
FAIL=0
RESULTS=()

green() { echo -e "\033[32m$1\033[0m"; }
red()   { echo -e "\033[31m$1\033[0m"; }
blue()  { echo -e "\033[34m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

run_suite() {
    local name="$1"
    local path="$2"
    local extra_args="${3:-}"

    blue "\n── Running: $name"

    if OWNEDPULSE_API_URL="$API_URL" OWNEDPULSE_PG_DSN="$PG_DSN" \
        python -m pytest "$path" \
            --tb=short \
            --no-header \
            -q \
            $extra_args \
            2>&1; then
        green "  PASSED: $name"
        RESULTS+=("PASS  $name")
        ((PASS++))
    else
        red "  FAILED: $name"
        RESULTS+=("FAIL  $name")
        ((FAIL++))
    fi
}

echo ""
echo "========================================"
echo " ownedpulse test runner v2"
echo " $(date '+%d/%m/%Y %H:%M:%S')"
echo " API: $API_URL"
echo " Suite: $SUITE"
echo "========================================"

# ── Pre-flight ────────────────────────────────────────────────────────────────
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/health" || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
    red "\nAPI not reachable at $API_URL (HTTP $HTTP_STATUS). Start the stack first."
    echo "  docker compose -f /opt/docker-compose/ownedpulse-api/docker-compose.yml up -d"
    echo "  docker compose -f /opt/docker-compose/ownedpulse-ui/docker-compose.yml up -d"
    exit 1
fi
green "\nAPI reachable — health OK\n"

# ── Check field names are correct before full run ─────────────────────────────
if [ "$SUITE" = "all" ] || [ "$SUITE" = "fields" ]; then
    yellow "── Field name correctness check (runs first)"
    if OWNEDPULSE_API_URL="$API_URL" OWNEDPULSE_PG_DSN="$PG_DSN" \
        python -m pytest tests/api/test_endpoints.py::TestCitationFields \
            --tb=short -q 2>&1; then
        green "  Field names: CORRECT"
    else
        red "  Field names: INCORRECT — stopping before further tests"
        red "  Check DEBRIEF.md and CLAUDE.md for correct Qdrant field names."
        exit 1
    fi
fi

# ── Suite selection ───────────────────────────────────────────────────────────
case "$SUITE" in

    api)
        run_suite "API endpoints" "tests/api/"
        ;;

    integ)
        run_suite "Integration / routing" "tests/integration/"
        ;;

    comply)
        run_suite "Compliance / Annex 11" "tests/compliance/"
        ;;

    e2e)
        run_suite "E2E UI (Playwright)" "tests/e2e/" "--headed"
        ;;

    fast)
        # No LLM inference — runs in < 60s
        run_suite "API endpoints"       "tests/api/test_endpoints.py::TestHealth tests/api/test_endpoints.py::TestCorpusStats tests/api/test_endpoints.py::TestQueryHistory"
        run_suite "Compliance / Annex 11" "tests/compliance/"
        ;;

    fields)
        run_suite "Field name correctness" "tests/api/test_endpoints.py::TestCitationFields"
        ;;

    all|*)
        run_suite "API endpoints"           "tests/api/"
        run_suite "Integration / routing"   "tests/integration/"
        run_suite "Compliance / Annex 11"   "tests/compliance/"
        run_suite "E2E UI (Playwright)"     "tests/e2e/" "--headed"
        ;;
esac

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo " Test results — $(date '+%d/%m/%Y %H:%M:%S')"
echo "========================================"
for result in "${RESULTS[@]}"; do
    if [[ "$result" == PASS* ]]; then
        green "  $result"
    else
        red   "  $result"
    fi
done
echo ""
echo " Suites passed: $PASS  |  Failed: $FAIL"
echo "========================================"

if [ "$FAIL" -eq 0 ]; then
    green " All suites passed. Phase G complete."
    exit 0
else
    red " $FAIL suite(s) failed. Check output above."
    exit 1
fi
