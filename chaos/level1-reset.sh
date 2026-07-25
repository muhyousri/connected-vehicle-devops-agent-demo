#!/usr/bin/env bash
# =============================================================================
# level1-reset.sh — Reset Kinesis Telemetry Flood
# =============================================================================
# The flood is self-resolving: once the burst stops, the ingestor catches up
# and iterator age drops. This script just confirms the system is recovering.
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-central-1}"
STREAM="${KINESIS_STREAM:-motoros3-vehicle-telemetry}"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🔄 LEVEL 1 RESET: Kinesis flood is self-resolving         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  The burst has stopped. Ingestor will catch up naturally.   ║${NC}"
echo -e "${GREEN}║  Iterator age will drop within 2-3 minutes.                 ║${NC}"
echo -e "${GREEN}║  Alarm will return to OK once metrics normalize.            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${BLUE}[INFO]${NC}  Checking current Kinesis stream health..."
aws kinesis describe-stream-summary --stream-name "$STREAM" --region "$REGION" \
  --query 'StreamDescriptionSummary.{Status:StreamStatus,Shards:OpenShardCount}' --output table 2>&1

echo ""
echo -e "${GREEN}  System will self-heal. No manual intervention needed.${NC}"
