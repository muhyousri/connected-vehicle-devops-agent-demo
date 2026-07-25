#!/usr/bin/env bash
# =============================================================================
# level3-inject.sh — ElastiCache Eviction Cascade
# =============================================================================
# Scenario: A parameter group change on Redis enables aggressive eviction.
# Vehicle position cache is evicted. vehicle-state-svc returns stale data.
# Geofence monitor sees vehicles "outside" zones → false notifications spike.
#
# RCA path (4 hops):
#   notification alarm → why so many? → geofence violations in audit_log
#   → why false? → positions are stale (check vehicle-state-svc logs)
#   → why stale? → Redis evictions (check ElastiCache metrics)
#   → why evictions? → parameter group changed (check CloudTrail)
#
# Difficulty: Hard (4-hop causality, no skill guidance)
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-central-1}"
NAMESPACE="${NAMESPACE:-motoros-prod}"
SECRET_ID="${SECRET_ID:-motoros3/db-credentials}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║  🔥 LEVEL 3: ElastiCache Eviction Cascade                   ║${NC}"
echo -e "${RED}║  Surface symptom: Notification rate spike                   ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

command -v kubectl >/dev/null 2>&1 || { echo "kubectl required"; exit 1; }

# Step 1: Change ElastiCache parameter group (creates CloudTrail evidence)
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 1/3: Applying aggressive eviction parameter group ━━━"
aws elasticache create-cache-parameter-group \
  --cache-parameter-group-name motoros3-cache-eviction-test \
  --cache-parameter-group-family redis7 \
  --description "Low maxmemory for eviction testing" \
  --region "$REGION" 2>/dev/null || true

aws elasticache modify-cache-parameter-group \
  --cache-parameter-group-name motoros3-cache-eviction-test \
  --parameter-name-values "ParameterName=maxmemory-policy,ParameterValue=allkeys-lru" \
  --region "$REGION" >/dev/null 2>&1 || true

aws elasticache modify-cache-cluster \
  --cache-cluster-id motoros3-cache \
  --cache-parameter-group-name motoros3-cache-eviction-test \
  --apply-immediately \
  --region "$REGION" >/dev/null 2>&1 || true
echo -e "${GREEN}[OK]${NC}    Parameter group 'motoros3-cache-eviction-test' applied (allkeys-lru)"

# Step 2: Fill Redis to trigger evictions
echo ""
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 2/3: Flooding Redis to trigger evictions ━━━"
REDIS_HOST=$(aws elasticache describe-cache-clusters \
  --cache-cluster-id motoros3-cache --show-cache-node-info \
  --region "$REGION" \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text 2>/dev/null)

kubectl exec deploy/vehicle-state-svc -n "$NAMESPACE" -- python3 -c "
import socket, json, random

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('${REDIS_HOST}', 6379))

# Write large keys to stress memory
for i in range(500):
    vin = f'vehicle:position:FLOOD-{i:04d}'
    data = 'X' * 8000  # 8KB per key = 4MB total, stresses t3.micro
    cmd = f'SET {vin} {data}\r\n'
    s.sendall(cmd.encode())
    s.recv(256)

# Check memory stats
s.sendall(b'INFO memory\r\n')
info = s.recv(4096).decode()
for line in info.split('\r\n'):
    if 'used_memory_human' in line or 'maxmemory_human' in line or 'evicted_keys' in line:
        print(f'  {line}')
s.close()
" 2>&1
echo -e "${GREEN}[OK]${NC}    Redis stressed with 500 large keys"

# Step 3: Insert false geofence notifications (the visible symptom)
echo ""
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 3/3: Inserting false geofence notifications ━━━"
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" --query 'SecretString' --output text)
DB_HOST=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['host'])")
DB_USER=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['username'])")
DB_PASS=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['password'])")

kubectl exec deploy/fleet-registry-svc -n "$NAMESPACE" -- env DB_HOST="$DB_HOST" DB_USER="$DB_USER" DB_PASS="$DB_PASS" python3 -c "
import psycopg2, os, random, json
from datetime import datetime, timezone, timedelta

conn = psycopg2.connect(
    host=os.environ['DB_HOST'], port=5432, dbname='motoros',
    user=os.environ['DB_USER'], password=os.environ['DB_PASS'])
cur = conn.cursor()

vins = ['WBA3A5G59DN123405','WBA3A5G59DN123406','5YJ3E1EA5LF123411',
        '5YJ3E1EA5LF123417','1FA6P8CF5L5123421','WDD2060421A123431',
        '5YJXCDE20HF123415','WBA7E2C50JG123401','5YJSA1E26MF123413',
        '1FA6P8CF5L5123423','WDD2060421A123439','WBA3A5G59DN123407']
geofences = ['Seattle Metro','LAX Airport Perimeter','EU Service Region (Frankfurt)',
             'Denver Curfew Zone','Coastal Express Depot']

now = datetime.now(timezone.utc)
for i in range(25):
    vin = random.choice(vins)
    fence = random.choice(geofences)
    ts = now - timedelta(minutes=random.randint(0, 4))
    cur.execute(
        '''INSERT INTO audit_log (action, actor, resource_type, resource_id, details, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)''',
        ('GEOFENCE_VIOLATION_NOTIFICATION', 'notification-svc', 'vehicle', vin,
         json.dumps({'geofence': fence, 'direction': 'EXIT', 'source': 'position_cache_stale',
                     'cached_position_age_sec': random.randint(120, 600),
                     'expected_zone': fence, 'vehicle_vin': vin}),
         ts.isoformat()))

conn.commit()
print(f'  Inserted 25 false geofence notification entries')
conn.close()
" 2>&1
echo -e "${GREEN}[OK]${NC}    25 false geofence notifications in audit_log"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ LEVEL 3 INJECTION COMPLETE                              ║${NC}"
echo -e "${GREEN}║  • Redis parameter group changed (eviction policy)          ║${NC}"
echo -e "${GREEN}║  • 500 large keys written to stress Redis memory            ║${NC}"
echo -e "${GREEN}║  • 25 false geofence notifications in audit_log             ║${NC}"
echo -e "${GREEN}║  • Alarm fires on notification rate within ~2 min           ║${NC}"
echo -e "${GREEN}║  To reset: ./level3-reset.sh                                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
