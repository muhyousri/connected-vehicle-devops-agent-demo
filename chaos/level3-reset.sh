#!/usr/bin/env bash
# =============================================================================
# level3-reset.sh — Reset ElastiCache Eviction Cascade
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-central-1}"
NAMESPACE="${NAMESPACE:-motoros-prod}"
SECRET_ID="${SECRET_ID:-motoros3/db-credentials}"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🔄 LEVEL 3 RESET: ElastiCache Eviction Cascade            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

command -v kubectl >/dev/null 2>&1 || { echo "kubectl required"; exit 1; }

# Step 1: Revert parameter group to default
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 1/3: Reverting Redis parameter group ━━━"
aws elasticache modify-cache-cluster \
  --cache-cluster-id motoros3-cache \
  --cache-parameter-group-name default.redis7 \
  --apply-immediately \
  --region "$REGION" >/dev/null 2>&1
echo -e "${GREEN}[OK]${NC}    Reverted to default.redis7 parameter group"

# Step 2: Flush Redis and remove flood keys
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 2/3: Flushing Redis ━━━"
REDIS_HOST=$(aws elasticache describe-cache-clusters \
  --cache-cluster-id motoros3-cache --show-cache-node-info \
  --region "$REGION" \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text 2>/dev/null)

kubectl exec deploy/vehicle-state-svc -n "$NAMESPACE" -- python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('${REDIS_HOST}', 6379))
s.sendall(b'FLUSHALL\r\n')
resp = s.recv(1024).decode()
print(f'  FLUSHALL: {resp.strip()}')
s.close()
" 2>&1
echo -e "${GREEN}[OK]${NC}    Redis flushed"

# Step 3: Remove false notifications from DB
echo -e "${BLUE}[INFO]${NC}  ━━━ Step 3/3: Removing false notifications from audit_log ━━━"
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" --query 'SecretString' --output text)
DB_HOST=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['host'])")
DB_USER=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['username'])")
DB_PASS=$(echo "$SECRET_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['password'])")

kubectl exec deploy/fleet-registry-svc -n "$NAMESPACE" -- env DB_HOST="$DB_HOST" DB_USER="$DB_USER" DB_PASS="$DB_PASS" python3 -c "
import psycopg2, os
conn = psycopg2.connect(host=os.environ['DB_HOST'], port=5432, dbname='motoros',
    user=os.environ['DB_USER'], password=os.environ['DB_PASS'])
cur = conn.cursor()
cur.execute(\"DELETE FROM audit_log WHERE action = 'GEOFENCE_VIOLATION_NOTIFICATION' AND created_at > NOW() - interval '24 hours'\")
conn.commit()
print(f'  Removed {cur.rowcount} false notification entries')
conn.close()
" 2>&1
echo -e "${GREEN}[OK]${NC}    Audit log cleaned"

# Cleanup parameter group (optional)
aws elasticache delete-cache-parameter-group \
  --cache-parameter-group-name motoros3-cache-eviction-test \
  --region "$REGION" 2>/dev/null || true

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ LEVEL 3 RESET COMPLETE                                  ║${NC}"
echo -e "${GREEN}║  • Redis parameter group reverted to default                ║${NC}"
echo -e "${GREEN}║  • Redis flushed                                            ║${NC}"
echo -e "${GREEN}║  • False notifications removed                              ║${NC}"
echo -e "${GREEN}║  Alarm will clear naturally within ~2 min                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
