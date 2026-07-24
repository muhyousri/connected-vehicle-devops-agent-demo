import os
import uuid
import random
import asyncio
from datetime import datetime, timezone, timedelta

import structlog
import psycopg2
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional

SERVICE_NAME = os.getenv("SERVICE_NAME", "warranty-claims-svc")
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

FAKE_VINS = [f"1MOTOR{random.randint(1000000000, 9999999999)}" for _ in range(20)]
DEALER_CODES = [f"DLR-{random.randint(1000, 9999)}" for _ in range(15)]
CLAIM_TYPES = ["powertrain", "electrical", "body", "suspension", "brakes", "hvac", "infotainment"]
CLAIM_STATUSES = ["submitted", "under_review", "approved", "denied", "paid"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class WarrantyClaimCreate(BaseModel):
    vehicle_vin: str
    dealer_code: str
    claim_type: str
    description: str
    mileage: int
    labor_hours: Optional[float] = None


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(5, 25), 2),
            "p95_latency_ms": round(random.uniform(25, 100), 2),
            "p99_latency_ms": round(random.uniform(100, 400), 2),
            "error_rate": round(random.uniform(0, 0.008), 4),
            "throughput_rps": round(random.uniform(30, 200), 1),
            "db_connection_count": random.randint(2, 10),
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


@app.post("/claims", status_code=201)
async def create_claim(claim: WarrantyClaimCreate):
    correlation_id = str(uuid.uuid4())
    claim_id = f"WC-{random.randint(100000, 999999)}"
    logger.info("warranty_claim_created", correlation_id=correlation_id,
                claim_id=claim_id, vehicle_vin=claim.vehicle_vin,
                dealer_code=claim.dealer_code, claim_type=claim.claim_type)
    return {
        "claim_id": claim_id,
        "status": "submitted",
        "vehicle_vin": claim.vehicle_vin,
        "dealer_code": claim.dealer_code,
        "estimated_payout": round(random.uniform(200, 5000), 2),
    }


@app.get("/claims/{claim_id}")
async def get_claim(claim_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("warranty_claim_query", correlation_id=correlation_id, claim_id=claim_id)
    return {
        "claim_id": claim_id,
        "vehicle_vin": random.choice(FAKE_VINS),
        "dealer_code": random.choice(DEALER_CODES),
        "claim_type": random.choice(CLAIM_TYPES),
        "status": random.choice(CLAIM_STATUSES),
        "submitted_at": (datetime.now(timezone.utc) - timedelta(days=random.randint(1, 90))).isoformat(),
        "amount": round(random.uniform(200, 8000), 2),
        "mileage": random.randint(5000, 80000),
    }


@app.get("/vehicles/{vin}/claims")
async def get_vehicle_claims(vin: str):
    correlation_id = str(uuid.uuid4())
    logger.info("vehicle_claims_query", correlation_id=correlation_id, vehicle_vin=vin)
    claims = [
        {
            "claim_id": f"WC-{random.randint(100000, 999999)}",
            "claim_type": random.choice(CLAIM_TYPES),
            "status": random.choice(CLAIM_STATUSES),
            "amount": round(random.uniform(200, 5000), 2),
        }
        for _ in range(random.randint(0, 5))
    ]
    return {"vehicle_vin": vin, "claims": claims, "total": len(claims)}
