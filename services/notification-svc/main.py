import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Optional

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-svc")
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

NOTIFICATION_CHANNELS = ["email", "sms", "push", "in_app", "webhook"]
NOTIFICATION_TYPES = ["ota_available", "maintenance_due", "recall_notice", "warranty_approved",
                      "fleet_alert", "geofence_violation", "speed_alert"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class NotificationRequest(BaseModel):
    recipient_id: str
    notification_type: str
    channels: List[str] = ["email"]
    vehicle_vin: Optional[str] = None
    fleet_id: Optional[str] = None
    message: str


async def notification_fanout_task():
    """Simulates fan-out of queued notifications."""
    await asyncio.sleep(5)
    while True:
        correlation_id = str(uuid.uuid4())
        batch_size = random.randint(5, 50)
        notification_type = random.choice(NOTIFICATION_TYPES)
        channels_used = random.sample(NOTIFICATION_CHANNELS, random.randint(1, 3))

        logger.info("notification_fanout", correlation_id=correlation_id,
                    batch_size=batch_size, notification_type=notification_type,
                    channels=channels_used,
                    delivered=batch_size - random.randint(0, 3),
                    failed=random.randint(0, 3))
        await asyncio.sleep(random.uniform(5, 12))


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(5, 30), 2),
            "p95_latency_ms": round(random.uniform(30, 150), 2),
            "p99_latency_ms": round(random.uniform(150, 500), 2),
            "error_rate": round(random.uniform(0, 0.01), 4),
            "throughput_rps": round(random.uniform(50, 500), 1),
            "queue_depth": random.randint(0, 2000),
            "db_connection_count": random.randint(2, 8),
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
    asyncio.create_task(notification_fanout_task())
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


@app.post("/notifications/send", status_code=202)
async def send_notification(notification: NotificationRequest):
    correlation_id = str(uuid.uuid4())
    notification_id = f"NOTIF-{random.randint(100000, 999999)}"
    logger.info("notification_queued", correlation_id=correlation_id,
                notification_id=notification_id,
                notification_type=notification.notification_type,
                channels=notification.channels,
                vehicle_vin=notification.vehicle_vin,
                fleet_id=notification.fleet_id)
    return {
        "notification_id": notification_id,
        "status": "queued",
        "channels": notification.channels,
        "estimated_delivery_seconds": random.randint(1, 30),
    }


@app.get("/notifications/{notification_id}/status")
async def notification_status(notification_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("notification_status_query", correlation_id=correlation_id,
                notification_id=notification_id)
    return {
        "notification_id": notification_id,
        "status": random.choice(["queued", "sending", "delivered", "failed"]),
        "channels_status": {
            ch: random.choice(["delivered", "pending", "failed"])
            for ch in random.sample(NOTIFICATION_CHANNELS, random.randint(1, 3))
        },
    }
