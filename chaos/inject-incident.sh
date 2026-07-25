#!/usr/bin/env bash
# =============================================================================
# inject-incident.sh — BMS Cold-Charging Rollback Cascade
# =============================================================================
# Scenario: BMS-2.8.1 firmware cold-charging bug triggers protective rollbacks
#           to BMS-2.7.0 when ambient temp drops below -2°C during charging.
# Uses kubectl exec + psycopg2 to run SQL against the fleet-registry DB.
# Usage:  ./inject-incident.sh
# Requires: kubectl, aws CLI, jq
# =============================================================================
set -euo pipefail

REGION="${REGION:-eu-central-1}"
NAMESPACE="${NAMESPACE:-motoros-prod}"
SECRET_ID="${SECRET_ID:-motoros3/db-credentials}"
DATABASE="${DATABASE:-motoros}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
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
echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║     🔥 CHAOS INJECTION: BMS Cold-Charging Rollback 🔥      ║${NC}"
echo -e "${RED}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${RED}║  Impact: 6 vehicles — P0A80 DTCs, BMS rollback to v2.7.0   ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
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

# --- Step 1: Insert DTC events -----------------------------------------------
log_info "━━━ Step 1/3: Injecting P0A80 DTC events for 6 vehicles ━━━"
VINS="'WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411','5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431'"

run_sql "Insert P0A80 DTC events" "INSERT INTO dtc_events (vehicle_vin,dtc_code,dtc_description,severity,ecu_source,status,occurrence_count,first_seen_at,last_seen_at) VALUES
('WBA3A5G59DN123405','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',3,NOW()-interval '2 hours',NOW()-interval '5 minutes'),
('WBA3A5G59DN123406','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',2,NOW()-interval '90 minutes',NOW()-interval '12 minutes'),
('5YJ3E1EA5LF123411','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',4,NOW()-interval '3 hours',NOW()-interval '3 minutes'),
('5YJ3E1EA5LF123417','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',2,NOW()-interval '1 hour',NOW()-interval '8 minutes'),
('1FA6P8CF5L5123421','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',5,NOW()-interval '4 hours',NOW()-interval '1 minute'),
('WDD2060421A123431','P0A80','Replace Energy Storage Unit','CRITICAL','BMS','ACTIVE',3,NOW()-interval '150 minutes',NOW()-interval '7 minutes');"
echo ""

# --- Step 2: Update BMS ECU status --------------------------------------------
log_info "━━━ Step 2/3: Setting BMS ECU status to ROLLBACK (v2.7.0) ━━━"
run_sql "Update BMS ECU to ROLLBACK" "UPDATE vehicle_ecus SET sw_status='ROLLBACK', sw_version='BMS-2.7.0', last_updated_at=NOW()
WHERE vehicle_vin IN ($VINS) AND ecu_type='BMS';"
echo ""

# --- Step 3: Insert telemetry events ------------------------------------------
log_info "━━━ Step 3/3: Injecting POWER_LIMIT_ACTIVE telemetry ━━━"
run_sql "Insert POWER_LIMIT_ACTIVE telemetry" "INSERT INTO telemetry_events (vehicle_vin,event_type,latitude,longitude,speed_kmh,soc_pct,fuel_level_pct,cell_voltage_min,cell_voltage_max,tire_pressure_fl,tire_pressure_fr,tire_pressure_rl,tire_pressure_rr,ambient_temp_c,engine_temp_c,odometer_km,event_timestamp) VALUES
('WBA3A5G59DN123405','POWER_LIMIT_ACTIVE',47.606,-122.332,35,72.00,NULL,2.81,4.15,242.0,241.5,238.0,237.5,-3.2,28.4,8950,NOW()-interval '5 minutes'),
('WBA3A5G59DN123406','POWER_LIMIT_ACTIVE',47.620,-122.349,0,45.00,NULL,2.76,4.12,238.0,237.5,235.0,234.5,-4.8,22.1,15720,NOW()-interval '12 minutes'),
('5YJ3E1EA5LF123411','POWER_LIMIT_ACTIVE',42.360,-71.059,28,38.50,NULL,2.69,4.08,235.0,236.0,232.0,233.0,-6.1,19.8,19850,NOW()-interval '3 minutes'),
('5YJ3E1EA5LF123417','POWER_LIMIT_ACTIVE',39.739,-104.990,42,55.00,NULL,2.83,4.14,240.0,239.5,237.0,236.5,-2.5,31.2,11280,NOW()-interval '8 minutes'),
('1FA6P8CF5L5123421','POWER_LIMIT_ACTIVE',48.857,2.352,15,22.00,NULL,2.58,4.02,245.0,244.5,242.0,241.5,-7.3,15.6,14380,NOW()-interval '1 minute'),
('WDD2060421A123431','POWER_LIMIT_ACTIVE',40.441,-79.996,0,31.00,NULL,2.72,4.09,248.0,247.5,245.0,244.5,-5.0,24.8,4560,NOW()-interval '7 minutes');"
echo ""

# --- Summary ------------------------------------------------------------------
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ CHAOS INJECTION COMPLETE                                 ║${NC}"
echo -e "${GREEN}║  • 6 P0A80 DTC events  • 6 BMS rollbacks (→ v2.7.0)         ║${NC}"
echo -e "${GREEN}║  • 6 POWER_LIMIT_ACTIVE telemetry events                     ║${NC}"
echo -e "${GREEN}║  To reset: ./reset-incident.sh                               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
