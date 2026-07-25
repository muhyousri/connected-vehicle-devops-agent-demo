#!/usr/bin/env bash
# =============================================================================
# level1-inject.sh — Kinesis Telemetry Flood
# =============================================================================
# Scenario: Telemetry producer rate spikes (simulating a fleet waking up after
# scheduled maintenance), overwhelming the Kinesis stream. The ingestor falls
# behind, iterator age grows, and the telemetry pipeline alarm fires.
#
# RCA path: alarm → Kinesis throttling metrics → producer rate spike
# Difficulty: Easy (single service, clear metrics)
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-central-1}"
NAMESPACE="${NAMESPACE:-motoros-prod}"
STREAM="${KINESIS_STREAM:-motoros3-vehicle-telemetry}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║  ⚡ LEVEL 1: Kinesis Telemetry Flood                        ║${NC}"
echo -e "${RED}║  Scenario: Fleet wake-up burst overwhelms telemetry stream  ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
command -v kubectl >/dev/null 2>&1 || { echo "kubectl required"; exit 1; }

echo -e "${BLUE}[INFO]${NC}  Flooding Kinesis stream with 5000 records (10 batches of 500)..."
echo -e "${BLUE}[INFO]${NC}  This simulates a fleet of 500 vehicles simultaneously reporting telemetry."
echo ""

kubectl exec deploy/telemetry-producer -n "$NAMESPACE" -- python3 -c "
import boto3, json, random, time
from datetime import datetime, timezone

kinesis = boto3.client('kinesis', region_name='${REGION}')
stream = '${STREAM}'
vins = [
    'WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411',
    '5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431',
    'WBA7E2C50JG123401','WBA7E2C50JG123402','5YJSA1E26MF123413',
    '5YJXCDE20HF123415','1FA6P8CF5L5123423','WDD2060421A123439',
]
events = ['HEARTBEAT','SPEED_EVENT','HARD_BRAKE','IGNITION_ON','CHARGING_START','DOOR_OPEN']

print('Starting flood...')
total_sent = 0
total_failed = 0
for batch in range(10):
    records = []
    for i in range(500):
        vin = random.choice(vins)
        r = {
            'vehicle_vin': vin,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': random.choice(events),
            'latitude': round(random.uniform(25, 52), 6),
            'longitude': round(random.uniform(-125, 14), 6),
            'speed_kmh': random.randint(0, 160),
            'soc_pct': round(random.uniform(10, 95), 2),
            'cell_voltage_min': round(random.uniform(3.1, 3.5), 2),
            'cell_voltage_max': round(random.uniform(3.9, 4.2), 2),
            'ambient_temp_c': round(random.uniform(-5, 35), 1),
            'odometer_km': random.randint(1000, 120000),
            'payload_padding': 'X' * 1500,
        }
        records.append({'Data': json.dumps(r).encode(), 'PartitionKey': vin})
    # PutRecords max is 500
    resp = kinesis.put_records(StreamName=stream, Records=records)
    failed = resp.get('FailedRecordCount', 0)
    total_sent += len(records)
    total_failed += failed
    print(f'  Batch {batch+1}/10: sent {len(records)}, failed {failed}')
    time.sleep(0.5)

print(f'Done: {total_sent} records sent, {total_failed} failed (throttled)')
" 2>&1

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ LEVEL 1 INJECTION COMPLETE                              ║${NC}"
echo -e "${GREEN}║  • 5000 records flooded to Kinesis                          ║${NC}"
echo -e "${GREEN}║  • Ingestor will fall behind (iterator age grows)           ║${NC}"
echo -e "${GREEN}║  • Alarm should fire within ~2 minutes                      ║${NC}"
echo -e "${GREEN}║  To reset: ./level1-reset.sh                                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
