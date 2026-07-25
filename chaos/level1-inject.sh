#!/usr/bin/env bash
# =============================================================================
# level1-inject.sh — Kinesis Telemetry Flood
# =============================================================================
# Scenario: Telemetry producer rate spikes (simulating a fleet waking up after
# scheduled maintenance window). The sustained burst overwhelms the stream
# causing write throttling and consumer lag (iterator age).
#
# RCA path: alarm → Kinesis throttling/iterator age → producer pod rate spike
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

command -v kubectl >/dev/null 2>&1 || { echo "kubectl required"; exit 1; }

echo -e "${BLUE}[INFO]${NC}  Sustained flood: 500 records/sec for 60 seconds (~30,000 records)"
echo -e "${BLUE}[INFO]${NC}  Each record ~5KB payload to saturate 1MB/s per-shard write limit"
echo -e "${BLUE}[INFO]${NC}  2 shards × 1MB/s = 2MB/s max. We'll push ~2.5MB/s to cause throttling"
echo ""

kubectl exec deploy/telemetry-producer -n "$NAMESPACE" -- python3 -c "
import boto3, json, random, time, sys
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

print('Starting sustained flood (60 seconds)...')
total_sent = 0
total_failed = 0
start = time.time()
batch_num = 0

while time.time() - start < 60:
    batch_num += 1
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
            'tire_pressure_fl': round(random.uniform(225, 255), 1),
            'tire_pressure_fr': round(random.uniform(225, 255), 1),
            'tire_pressure_rl': round(random.uniform(220, 250), 1),
            'tire_pressure_rr': round(random.uniform(220, 250), 1),
            'engine_temp_c': round(random.uniform(30, 105), 1),
            'payload': 'X' * 3500,
        }
        records.append({'Data': json.dumps(r).encode(), 'PartitionKey': vin})
    try:
        resp = kinesis.put_records(StreamName=stream, Records=records)
        failed = resp.get('FailedRecordCount', 0)
        total_sent += len(records)
        total_failed += failed
        if batch_num % 5 == 0:
            elapsed = int(time.time() - start)
            rate = total_sent / max(elapsed, 1)
            print(f'  [{elapsed}s] batch {batch_num}: sent {total_sent}, failed {total_failed}, rate ~{rate:.0f} rec/s')
            sys.stdout.flush()
    except Exception as e:
        print(f'  Error: {e}')
    time.sleep(0.1)

elapsed = int(time.time() - start)
print(f'Done: {total_sent} records in {elapsed}s, {total_failed} throttled')
" 2>&1

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ LEVEL 1 INJECTION COMPLETE                              ║${NC}"
echo -e "${GREEN}║  • Sustained flood sent for 60 seconds                      ║${NC}"
echo -e "${GREEN}║  • Kinesis WriteProvisionedThroughputExceeded expected       ║${NC}"
echo -e "${GREEN}║  • Ingestor iterator age will spike                         ║${NC}"
echo -e "${GREEN}║  • Check: GetRecords.IteratorAgeMilliseconds in CloudWatch  ║${NC}"
echo -e "${GREEN}║  To reset: ./level1-reset.sh (self-resolving)               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
