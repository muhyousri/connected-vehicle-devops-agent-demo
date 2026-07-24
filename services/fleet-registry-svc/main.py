import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

SERVICE_NAME = os.getenv("SERVICE_NAME", "fleet-registry-svc")
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

FAKE_FLEETS = [
    {"fleet_id": f"FLT-{i:04d}", "name": f"Fleet {name}", "size": random.randint(10, 500)}
    for i, name in enumerate(["West Coast", "East Coast", "Central", "Southwest", "Northwest",
                               "Southeast", "Midwest", "Mountain", "Pacific", "Atlantic"], 1)
]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class FleetCreate(BaseModel):
    name: str
    region: str
    max_vehicles: int = 100


class FleetUpdate(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    max_vehicles: Optional[int] = None


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(2, 10), 2),
            "p95_latency_ms": round(random.uniform(10, 50), 2),
            "p99_latency_ms": round(random.uniform(50, 150), 2),
            "error_rate": round(random.uniform(0, 0.003), 4),
            "throughput_rps": round(random.uniform(100, 800), 1),
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


@app.get("/fleets")
async def list_fleets():
    correlation_id = str(uuid.uuid4())
    logger.info("fleet_list_query", correlation_id=correlation_id)
    return {"fleets": FAKE_FLEETS, "total": len(FAKE_FLEETS)}


@app.get("/fleets/{fleet_id}")
async def get_fleet(fleet_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("fleet_get", correlation_id=correlation_id, fleet_id=fleet_id)
    fleet = next((f for f in FAKE_FLEETS if f["fleet_id"] == fleet_id), None)
    if not fleet:
        raise HTTPException(status_code=404, detail="Fleet not found")
    return fleet


@app.post("/fleets", status_code=201)
async def create_fleet(fleet: FleetCreate):
    correlation_id = str(uuid.uuid4())
    fleet_id = f"FLT-{random.randint(1000, 9999)}"
    logger.info("fleet_created", correlation_id=correlation_id, fleet_id=fleet_id, name=fleet.name)
    return {"fleet_id": fleet_id, "name": fleet.name, "region": fleet.region, "status": "created"}


@app.put("/fleets/{fleet_id}")
async def update_fleet(fleet_id: str, fleet: FleetUpdate):
    correlation_id = str(uuid.uuid4())
    logger.info("fleet_updated", correlation_id=correlation_id, fleet_id=fleet_id)
    return {"fleet_id": fleet_id, "status": "updated"}


@app.delete("/fleets/{fleet_id}")
async def delete_fleet(fleet_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("fleet_deleted", correlation_id=correlation_id, fleet_id=fleet_id)
    return {"fleet_id": fleet_id, "status": "deleted"}
