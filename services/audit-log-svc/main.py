import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional

SERVICE_NAME = os.getenv("SERVICE_NAME", "audit-log-svc")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "motoros")
DB_USER = os.getenv("DB_USER", "motoros")
DB_PASSWORD = os.getenv("DB_PASSWORD", "motoros")
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(service=SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)

AUDIT_ACTIONS = ["vehicle.state_update", "fleet.created", "fleet.deleted", "campaign.started",
                 "campaign.paused", "firmware.distributed", "order.created", "order.shipped",
                 "claim.submitted", "claim.approved", "user.login", "user.logout",
                 "notification.sent", "config.changed"]
ACTORS = ["system", "admin@motoros.io", "fleet-mgr@motoros.io", "dealer-ops@motoros.io",
           "svc:telemetry-processor", "svc:ota-campaign-svc", "svc:notification-svc"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class AuditEntry(BaseModel):
    action: str
    actor: str
    resource_type: str
    resource_id: str
    vehicle_vin: Optional[str] = None
    fleet_id: Optional[str] = None
    details: Optional[dict] = None


async def audit_writer_task():
    """Background: simulates writing audit entries from queue."""
    await asyncio.sleep(4)
    while True:
        correlation_id = str(uuid.uuid4())
        action = random.choice(AUDIT_ACTIONS)
        actor = random.choice(ACTORS)
        logger.info("audit_entry_written", correlation_id=correlation_id,
                    action=action, actor=actor,
                    resource_id=str(uuid.uuid4())[:8])

        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("audit_write_failed", correlation_id=correlation_id, error=str(e))
                conn.close()

        await asyncio.sleep(random.uniform(3, 8))


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(1, 5), 2),
            "p95_latency_ms": round(random.uniform(5, 20), 2),
            "p99_latency_ms": round(random.uniform(20, 60), 2),
            "error_rate": round(random.uniform(0, 0.002), 4),
            "throughput_rps": round(random.uniform(200, 2000), 1),
            "db_connection_count": random.randint(3, 12),
            "queue_depth": random.randint(0, 500),
        }
        logger.info("metrics_emitted", **metrics)
        await asyncio.sleep(15)


async def db_keepalive_task():
    await asyncio.sleep(8)
    while True:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                conn.close()
            except Exception:
                pass
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup():
    logger.info("service_starting", service=SERVICE_NAME)
    asyncio.create_task(audit_writer_task())
    asyncio.create_task(metrics_emitter_task())
    asyncio.create_task(db_keepalive_task())


@app.get("/health")
async def health():
    return {"status": "healthy", "service": SERVICE_NAME, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
async def ready():
    conn = get_db_connection()
    if conn:
        conn.close()
        return {"status": "ready", "service": SERVICE_NAME}
    return {"status": "not_ready", "service": SERVICE_NAME, "reason": "db_unavailable"}


@app.post("/audit", status_code=201)
async def create_audit_entry(entry: AuditEntry):
    correlation_id = str(uuid.uuid4())
    audit_id = f"AUD-{random.randint(100000, 999999)}"
    logger.info("audit_entry_created", correlation_id=correlation_id,
                audit_id=audit_id, action=entry.action, actor=entry.actor,
                vehicle_vin=entry.vehicle_vin, fleet_id=entry.fleet_id)
    return {
        "audit_id": audit_id,
        "action": entry.action,
        "actor": entry.actor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "recorded",
    }


@app.get("/audit/search")
async def search_audit(action: Optional[str] = None, actor: Optional[str] = None,
                       resource_id: Optional[str] = None, limit: int = 50):
    correlation_id = str(uuid.uuid4())
    logger.info("audit_search", correlation_id=correlation_id,
                action=action, actor=actor, limit=limit)
    entries = [
        {
            "audit_id": f"AUD-{random.randint(100000, 999999)}",
            "action": action or random.choice(AUDIT_ACTIONS),
            "actor": actor or random.choice(ACTORS),
            "resource_id": resource_id or str(uuid.uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for _ in range(min(limit, random.randint(5, 30)))
    ]
    return {"entries": entries, "total": len(entries), "limit": limit}
