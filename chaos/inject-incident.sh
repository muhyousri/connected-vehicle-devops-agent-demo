#!/usr/bin/env bash
# =============================================================================
# inject-incident.sh — BMS Cold-Charging Rollback Cascade
# =============================================================================
# Scenario: BMS-2.8.1 firmware has a cold-charging bug that triggers protective
#           rollbacks to BMS-2.7.0 when ambient temperature drops below -2°C
#           during charging. This causes P0A80 DTCs and POWER_LIMIT_ACTIVE
#           telemetry events across affected vehicles.
#
# What this script does:
#   1. Inserts P0A80 DTC events for 6 affected vehicles
#   2. Sets BMS ECU status to ROLLBACK (reverted to BMS-2.7.0)
#   3. Inserts anomalous POWER_LIMIT_ACTIVE telemetry with low cell voltages
#
# What this script does NOT do:
#   - Trigger any CloudWatch alarms manually
#   - Crash pods or modify Kubernetes resources
#   - Affect any real vehicle systems
#
# Usage:
#   ./inject-incident.sh
#
# Environment variables (optional overrides):
#   CLUSTER_ARN  - Aurora Serverless cluster ARN
#   SECRET_ARN   - Secrets Manager ARN for DB credentials
#   DATABASE     - Database name (default: motoros)
#   AWS_REGION   - AWS region (default: eu-central-1)
# =============================================================================

set -euo pipefail

# --- Configuration -----------------------------------------------------------
AWS_REGION="${AWS_REGION:-eu-central-1}"
DATABASE="${DATABASE:-motoros}"
STACK_NAME="${STACK_NAME:-motoros3-Aurora}"
DB_CLUSTER_ID="${DB_CLUSTER_ID:-motoros3-db}"

# --- Colors for output -------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Helper functions --------------------------------------------------------
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

die() {
    log_error "$*"
    exit 1
}

# Execute a SQL statement via RDS Data API
execute_sql() {
    local description="$1"
    local sql="$2"

    log_info "Executing: ${description}..."

    local result
    if result=$(aws rds-data execute-statement \
        --resource-arn "$CLUSTER_ARN" \
        --secret-arn "$SECRET_ARN" \
        --database "$DATABASE" \
        --sql "$sql" \
        --region "$AWS_REGION" \
        --output json 2>&1); then
        local affected
        affected=$(echo "$result" | grep -o '"numberOfRecordsUpdated":[0-9]*' | cut -d: -f2 || echo "N/A")
        log_ok "${description} — records affected: ${affected}"
    else
        log_error "Failed: ${description}"
        log_error "$result"
        return 1
    fi
}

# --- Auto-discover cluster ARN and secret ARN --------------------------------
discover_resources() {
    log_info "Discovering Aurora cluster resources..."

    # If CLUSTER_ARN is already set, skip discovery
    if [[ -n "${CLUSTER_ARN:-}" && -n "${SECRET_ARN:-}" ]]; then
        log_info "Using provided CLUSTER_ARN and SECRET_ARN from environment"
        return 0
    fi

    # Method 1: Try CloudFormation stack outputs
    log_info "Attempting discovery via CloudFormation stack: ${STACK_NAME}..."
    local stack_outputs
    if stack_outputs=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs" \
        --output json 2>/dev/null); then

        CLUSTER_ARN=$(echo "$stack_outputs" | \
            python3 -c "import sys,json; outputs=json.load(sys.stdin); print(next((o['OutputValue'] for o in outputs if o['OutputKey']=='AuroraEndpoint'),''))" 2>/dev/null || true)
        SECRET_ARN=$(echo "$stack_outputs" | \
            python3 -c "import sys,json; outputs=json.load(sys.stdin); print(next((o['OutputValue'] for o in outputs if o['OutputKey']=='AuroraSecretArn'),''))" 2>/dev/null || true)

        if [[ -n "$CLUSTER_ARN" && -n "$SECRET_ARN" ]]; then
            log_ok "Discovered resources from CloudFormation stack"
            return 0
        fi
        log_warn "CloudFormation stack found but missing expected outputs"
    fi

    # Method 2: Try RDS describe-db-clusters
    log_info "Attempting discovery via RDS describe-db-clusters: ${DB_CLUSTER_ID}..."
    local cluster_info
    if cluster_info=$(aws rds describe-db-clusters \
        --db-cluster-identifier "$DB_CLUSTER_ID" \
        --region "$AWS_REGION" \
        --output json 2>/dev/null); then

        CLUSTER_ARN=$(echo "$cluster_info" | \
            python3 -c "import sys,json; print(json.load(sys.stdin)['DBClusters'][0]['DBClusterArn'])" 2>/dev/null || true)

        if [[ -n "$CLUSTER_ARN" ]]; then
            # Derive secret ARN from associated secrets (convention: motoros3-db-secret)
            SECRET_ARN=$(aws secretsmanager list-secrets \
                --region "$AWS_REGION" \
                --filter Key=name,Values=motoros3 \
                --query "SecretList[0].ARN" \
                --output text 2>/dev/null || true)

            if [[ -n "$SECRET_ARN" && "$SECRET_ARN" != "None" ]]; then
                log_ok "Discovered resources from RDS + Secrets Manager"
                return 0
            fi
        fi
    fi

    die "Could not auto-discover CLUSTER_ARN and SECRET_ARN. Please set them as environment variables."
}

# =============================================================================
# MAIN
# =============================================================================

echo ""
echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║     🔥 CHAOS INJECTION: BMS Cold-Charging Rollback 🔥      ║${NC}"
echo -e "${RED}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${RED}║  Scenario: BMS-2.8.1 firmware cold-charging bug             ║${NC}"
echo -e "${RED}║  Impact:   6 vehicles experiencing protective rollbacks     ║${NC}"
echo -e "${RED}║  DTCs:     P0A80 (Replace Energy Storage Unit)              ║${NC}"
echo -e "${RED}║  ECU:      BMS rolling back to v2.7.0                       ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Discover Aurora resources
discover_resources

log_info "Configuration:"
log_info "  Region:      ${AWS_REGION}"
log_info "  Database:    ${DATABASE}"
log_info "  Cluster ARN: ${CLUSTER_ARN}"
log_info "  Secret ARN:  ${SECRET_ARN}"
echo ""

# --- Step 1: Insert DTC events -----------------------------------------------
log_info "━━━ Step 1/3: Injecting P0A80 DTC events for 6 vehicles ━━━"

DTC_SQL="INSERT INTO dtc_events (vehicle_vin, dtc_code, dtc_description, severity, ecu_source, status, occurrence_count, first_seen_at, last_seen_at) VALUES \
('WBA3A5G59DN123405', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 3, NOW() - interval '2 hours', NOW() - interval '5 minutes'), \
('WBA3A5G59DN123406', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 2, NOW() - interval '90 minutes', NOW() - interval '12 minutes'), \
('5YJ3E1EA5LF123411', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 4, NOW() - interval '3 hours', NOW() - interval '3 minutes'), \
('5YJ3E1EA5LF123417', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 2, NOW() - interval '1 hour', NOW() - interval '8 minutes'), \
('1FA6P8CF5L5123421', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 5, NOW() - interval '4 hours', NOW() - interval '1 minute'), \
('WDD2060421A123431', 'P0A80', 'Replace Energy Storage Unit', 'CRITICAL', 'BMS', 'ACTIVE', 3, NOW() - interval '2.5 hours', NOW() - interval '7 minutes');"

execute_sql "Insert P0A80 DTC events for 6 affected vehicles" "$DTC_SQL"
echo ""

# --- Step 2: Update BMS ECU status to ROLLBACK --------------------------------
log_info "━━━ Step 2/3: Setting BMS ECU status to ROLLBACK (v2.7.0) ━━━"

ECU_SQL="UPDATE vehicle_ecus SET sw_status = 'ROLLBACK', sw_version = 'BMS-2.7.0', last_updated_at = NOW() \
WHERE vehicle_vin IN ('WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411','5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431') \
AND ecu_type = 'BMS';"

execute_sql "Update BMS ECU to ROLLBACK state" "$ECU_SQL"
echo ""

# --- Step 3: Insert anomalous telemetry events --------------------------------
log_info "━━━ Step 3/3: Injecting POWER_LIMIT_ACTIVE telemetry (low cell voltage, cold temps) ━━━"

TELEMETRY_SQL="INSERT INTO telemetry_events (vehicle_vin, event_type, latitude, longitude, speed_kmh, soc_pct, fuel_level_pct, cell_voltage_min, cell_voltage_max, tire_pressure_fl, tire_pressure_fr, tire_pressure_rl, tire_pressure_rr, ambient_temp_c, engine_temp_c, odometer_km, event_timestamp) VALUES \
('WBA3A5G59DN123405', 'POWER_LIMIT_ACTIVE', 47.606, -122.332, 35, 72.00, NULL, 2.81, 4.15, 242.0, 241.5, 238.0, 237.5, -3.2, 28.4, 8950, NOW() - interval '5 minutes'), \
('WBA3A5G59DN123406', 'POWER_LIMIT_ACTIVE', 47.620, -122.349, 0, 45.00, NULL, 2.76, 4.12, 238.0, 237.5, 235.0, 234.5, -4.8, 22.1, 15720, NOW() - interval '12 minutes'), \
('5YJ3E1EA5LF123411', 'POWER_LIMIT_ACTIVE', 42.360, -71.059, 28, 38.50, NULL, 2.69, 4.08, 235.0, 236.0, 232.0, 233.0, -6.1, 19.8, 19850, NOW() - interval '3 minutes'), \
('5YJ3E1EA5LF123417', 'POWER_LIMIT_ACTIVE', 39.739, -104.990, 42, 55.00, NULL, 2.83, 4.14, 240.0, 239.5, 237.0, 236.5, -2.5, 31.2, 11280, NOW() - interval '8 minutes'), \
('1FA6P8CF5L5123421', 'POWER_LIMIT_ACTIVE', 48.857, 2.352, 15, 22.00, NULL, 2.58, 4.02, 245.0, 244.5, 242.0, 241.5, -7.3, 15.6, 14380, NOW() - interval '1 minute'), \
('WDD2060421A123431', 'POWER_LIMIT_ACTIVE', 40.441, -79.996, 0, 31.00, NULL, 2.72, 4.09, 248.0, 247.5, 245.0, 244.5, -5.0, 24.8, 4560, NOW() - interval '7 minutes');"

execute_sql "Insert POWER_LIMIT_ACTIVE telemetry events" "$TELEMETRY_SQL"
echo ""

# --- Summary ------------------------------------------------------------------
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✅ CHAOS INJECTION COMPLETE                        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Injected:                                                   ║${NC}"
echo -e "${GREEN}║    • 6 P0A80 DTC events (BMS critical)                       ║${NC}"
echo -e "${GREEN}║    • 6 BMS ECU rollbacks (2.8.1 → 2.7.0)                     ║${NC}"
echo -e "${GREEN}║    • 6 POWER_LIMIT_ACTIVE telemetry events                   ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}║  Affected VINs:                                              ║${NC}"
echo -e "${GREEN}║    WBA3A5G59DN123405  WBA3A5G59DN123406                       ║${NC}"
echo -e "${GREEN}║    5YJ3E1EA5LF123411  5YJ3E1EA5LF123417                       ║${NC}"
echo -e "${GREEN}║    1FA6P8CF5L5123421  WDD2060421A123431                       ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}║  To reset: ./reset-incident.sh                               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
