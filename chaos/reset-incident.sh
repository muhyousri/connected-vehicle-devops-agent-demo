#!/usr/bin/env bash
# =============================================================================
# reset-incident.sh — Reverse BMS Cold-Charging Rollback Cascade
# =============================================================================
# This script cleans up all data injected by inject-incident.sh:
#   1. Removes P0A80 DTC events created in the last 24 hours
#   2. Restores BMS ECU status to UP_TO_DATE (v2.8.1) for affected vehicles
#   3. Removes POWER_LIMIT_ACTIVE telemetry events from the last 24 hours
#
# Usage:
#   ./reset-incident.sh
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
CYAN='\033[0;36m'
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

        CLUSTER_ARN=$(aws rds describe-db-clusters --db-cluster-identifier "$DB_CLUSTER_ID" \
            --region "$AWS_REGION" --query 'DBClusters[0].DBClusterArn' --output text 2>/dev/null || true)
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
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     🔄 CHAOS RESET: BMS Cold-Charging Rollback Cleanup 🔄  ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║  Reversing: BMS-2.8.1 firmware cold-charging scenario       ║${NC}"
echo -e "${CYAN}║  Actions:   Remove DTCs, restore ECUs, clean telemetry      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Discover Aurora resources
discover_resources

log_info "Configuration:"
log_info "  Region:      ${AWS_REGION}"
log_info "  Database:    ${DATABASE}"
log_info "  Cluster ARN: ${CLUSTER_ARN}"
log_info "  Secret ARN:  ${SECRET_ARN}"
echo ""

# --- Step 1: Remove injected DTC events ---------------------------------------
log_info "━━━ Step 1/3: Removing injected P0A80 DTC events (last 24h) ━━━"

DELETE_DTC_SQL="DELETE FROM dtc_events \
WHERE dtc_code = 'P0A80' \
AND status = 'ACTIVE' \
AND first_seen_at > NOW() - interval '24 hours';"

execute_sql "Delete recent P0A80 DTC events" "$DELETE_DTC_SQL"
echo ""

# --- Step 2: Restore BMS ECU status -------------------------------------------
log_info "━━━ Step 2/3: Restoring BMS ECU to UP_TO_DATE (v2.8.1) ━━━"

RESTORE_ECU_SQL="UPDATE vehicle_ecus SET sw_status = 'UP_TO_DATE', sw_version = 'BMS-2.8.1', last_updated_at = NOW() \
WHERE vehicle_vin IN ('WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411','5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431') \
AND ecu_type = 'BMS';"

execute_sql "Restore BMS ECU status to UP_TO_DATE" "$RESTORE_ECU_SQL"
echo ""

# --- Step 3: Remove injected telemetry events ---------------------------------
log_info "━━━ Step 3/3: Removing POWER_LIMIT_ACTIVE telemetry (last 24h) ━━━"

DELETE_TELEMETRY_SQL="DELETE FROM telemetry_events \
WHERE event_type = 'POWER_LIMIT_ACTIVE' \
AND event_timestamp > NOW() - interval '24 hours';"

execute_sql "Delete recent POWER_LIMIT_ACTIVE telemetry events" "$DELETE_TELEMETRY_SQL"
echo ""

# --- Summary ------------------------------------------------------------------
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✅ CHAOS RESET COMPLETE                            ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Restored:                                                   ║${NC}"
echo -e "${GREEN}║    • Removed P0A80 DTC events (last 24h)                     ║${NC}"
echo -e "${GREEN}║    • BMS ECU restored to UP_TO_DATE / v2.8.1                 ║${NC}"
echo -e "${GREEN}║    • Removed POWER_LIMIT_ACTIVE telemetry (last 24h)         ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}║  Affected VINs (restored):                                   ║${NC}"
echo -e "${GREEN}║    WBA3A5G59DN123405  WBA3A5G59DN123406                       ║${NC}"
echo -e "${GREEN}║    5YJ3E1EA5LF123411  5YJ3E1EA5LF123417                       ║${NC}"
echo -e "${GREEN}║    1FA6P8CF5L5123421  WDD2060421A123431                       ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}║  System should return to normal within monitoring cycle.     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
