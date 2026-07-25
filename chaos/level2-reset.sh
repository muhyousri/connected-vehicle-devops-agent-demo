#!/usr/bin/env bash
# =============================================================================
# reset-incident.sh — Reverse BMS Cold-Charging Rollback Cascade
# =============================================================================
# Cleans up all data injected by inject-incident.sh:
#   1. Removes P0A80 DTC events (last 24h)
#   2. Restores BMS ECU status to UP_TO_DATE (v2.8.1)
#   3. Removes POWER_LIMIT_ACTIVE telemetry events (last 24h)
# Uses kubectl exec + psycopg2 to run SQL against the fleet-registry DB.
# Usage:  ./reset-incident.sh
# Requires: kubectl, aws CLI, jq
# =============================================================================
set -euo pipefail

REGION="${REGION:-eu-central-1}"
NAMESPACE="${NAMESPACE:-motoros-prod}"
SECRET_ID="${SECRET_ID:-motoros3/db-credentials}"
DATABASE="${DATABASE:-motoros}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die() { log_error "$*"; exit 1; }

run_sql() {
    local desc="$1" sql="$2"
    log_info "Executing: ${desc}..."
    local out
    if out=$(kubectl exec deploy/fleet-registry-svc -n "$NAMESPACE" -- \
        env DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" DB_USER="$DB_USER" DB_PASS="$DB_PASS" DB_NAME="$DATABASE" \
        python3 -c '
import os, psycopg2
conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
    user=os.environ["DB_USER"], password=os.environ["DB_PASS"], dbname=os.environ["DB_NAME"])
conn.autocommit = True
cur = conn.cursor()
cur.execute("""'"$sql"'""")
print(f"Rows affected: {cur.rowcount}")
cur.close(); conn.close()
' 2>&1); then
        log_ok "${desc} — ${out}"
    else
        log_error "Failed: ${desc}"; echo "$out" >&2; return 1
    fi
}

# === MAIN ====================================================================
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     🔄 CHAOS RESET: BMS Cold-Charging Rollback Cleanup 🔄  ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║  Reversing: BMS-2.8.1 cold-charging scenario (6 vehicles)   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

command -v kubectl >/dev/null 2>&1 || die "kubectl not found"
command -v jq >/dev/null 2>&1 || die "jq not found"

log_info "Fetching DB credentials from Secrets Manager..."
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" \
    --query 'SecretString' --output text 2>&1) || die "Failed to fetch secret: $SECRET_JSON"
DB_HOST=$(echo "$SECRET_JSON" | jq -r '.host')
DB_PORT=$(echo "$SECRET_JSON" | jq -r '.port')
DB_USER=$(echo "$SECRET_JSON" | jq -r '.username')
DB_PASS=$(echo "$SECRET_JSON" | jq -r '.password')
[[ -n "$DB_HOST" && "$DB_HOST" != "null" ]] || die "Could not extract DB host from secret"
log_ok "Credentials retrieved (host: ${DB_HOST})"
echo ""

VINS="'WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411','5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431'"

# --- Step 1: Remove injected DTC events ---------------------------------------
log_info "━━━ Step 1/3: Removing P0A80 DTC events (last 24h) ━━━"
run_sql "Delete recent P0A80 DTC events" \
    "DELETE FROM dtc_events WHERE dtc_code='P0A80' AND status='ACTIVE' AND first_seen_at > NOW() - interval '24 hours';"
echo ""

# --- Step 2: Restore BMS ECU status -------------------------------------------
log_info "━━━ Step 2/3: Restoring BMS ECU to UP_TO_DATE (v2.8.1) ━━━"
run_sql "Restore BMS ECU status" \
    "UPDATE vehicle_ecus SET sw_status='UP_TO_DATE', sw_version='BMS-2.8.1', last_updated_at=NOW()
WHERE vehicle_vin IN ($VINS) AND ecu_type='BMS';"
echo ""

# --- Step 3: Remove injected telemetry events ---------------------------------
log_info "━━━ Step 3/3: Removing POWER_LIMIT_ACTIVE telemetry (last 24h) ━━━"
run_sql "Delete recent POWER_LIMIT_ACTIVE telemetry" \
    "DELETE FROM telemetry_events WHERE event_type='POWER_LIMIT_ACTIVE' AND event_timestamp > NOW() - interval '24 hours';"
echo ""

# --- Summary ------------------------------------------------------------------
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ CHAOS RESET COMPLETE                                     ║${NC}"
echo -e "${GREEN}║  • Removed P0A80 DTC events (last 24h)                       ║${NC}"
echo -e "${GREEN}║  • BMS ECU restored to UP_TO_DATE / v2.8.1                   ║${NC}"
echo -e "${GREEN}║  • Removed POWER_LIMIT_ACTIVE telemetry (last 24h)           ║${NC}"
echo -e "${GREEN}║  System should return to normal within monitoring cycle.     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
