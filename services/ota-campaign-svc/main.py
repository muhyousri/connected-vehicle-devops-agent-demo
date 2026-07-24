import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List

SERVICE_NAME = os.getenv("SERVICE_NAME", "ota-campaign-svc")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "motoros")
DB_USER = os.getenv("DB_USER", "motoros")
DB_PASSWORD = os.getenv("DB_PASSWORD", "motoros")

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(service=SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)

CAMPAIGN_STATUSES = ["draft", "scheduled", "rolling_out", "paused", "completed", "cancelled"]
FIRMWARE_VERSIONS = ["TCU-4.2.0", "TCU-4.3.0", "IVI-3.1.4", "BMS-2.8.1", "ADAS-1.5.0", "VCU-2.4.0"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class CampaignCreate(BaseModel):
    name: str
    firmware_version: str
    target_fleet_ids: List[str] = []
    rollout_percentage: int = 10
    description: Optional[str] = None


async def campaign_monitor_task():
    """Simulates monitoring active OTA campaigns."""
    await asyncio.sleep(7)
    while True:
        ota_campaign_id = f"OTA-{random.randint(1000, 9999)}"
        logger.info("campaign_progress_check", ota_campaign_id=ota_campaign_id,
                    progress_pct=random.randint(0, 100),
                    vehicles_updated=random.randint(10, 5000),
                    vehicles_pending=random.randint(0, 2000),
                    failures=random.randint(0, 50))
        await asyncio.sleep(12)


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(3, 15), 2),
            "p95_latency_ms": round(random.uniform(15, 60), 2),
            "p99_latency_ms": round(random.uniform(60, 200), 2),
            "error_rate": round(random.uniform(0, 0.005), 4),
            "throughput_rps": round(random.uniform(20, 150), 1),
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
    asyncio.create_task(campaign_monitor_task())
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


@app.post("/campaigns", status_code=201)
async def create_campaign(campaign: CampaignCreate):
    correlation_id = str(uuid.uuid4())
    ota_campaign_id = f"OTA-{random.randint(1000, 9999)}"
    logger.info("campaign_created", correlation_id=correlation_id,
                ota_campaign_id=ota_campaign_id, firmware_version=campaign.firmware_version,
                target_fleets=len(campaign.target_fleet_ids))
    return {
        "ota_campaign_id": ota_campaign_id,
        "name": campaign.name,
        "firmware_version": campaign.firmware_version,
        "status": "draft",
        "rollout_percentage": campaign.rollout_percentage,
    }


@app.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("campaign_query", correlation_id=correlation_id, ota_campaign_id=campaign_id)
    return {
        "ota_campaign_id": campaign_id,
        "name": f"Campaign {campaign_id}",
        "firmware_version": random.choice(FIRMWARE_VERSIONS),
        "status": random.choice(CAMPAIGN_STATUSES),
        "progress_pct": random.randint(0, 100),
        "vehicles_targeted": random.randint(100, 10000),
        "vehicles_updated": random.randint(0, 8000),
        "vehicles_failed": random.randint(0, 100),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/campaigns")
async def list_campaigns():
    correlation_id = str(uuid.uuid4())
    logger.info("campaigns_list", correlation_id=correlation_id)
    campaigns = [
        {
            "ota_campaign_id": f"OTA-{random.randint(1000, 9999)}",
            "name": f"Firmware Update {v}",
            "status": random.choice(CAMPAIGN_STATUSES),
            "firmware_version": v,
        }
        for v in FIRMWARE_VERSIONS
    ]
    return {"campaigns": campaigns, "total": len(campaigns)}


@app.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("campaign_started", correlation_id=correlation_id, ota_campaign_id=campaign_id)
    return {"ota_campaign_id": campaign_id, "status": "rolling_out"}


@app.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("campaign_paused", correlation_id=correlation_id, ota_campaign_id=campaign_id)
    return {"ota_campaign_id": campaign_id, "status": "paused"}
