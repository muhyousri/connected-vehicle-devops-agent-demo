import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException

SERVICE_NAME = os.getenv("SERVICE_NAME", "vehicle-state-svc")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "motoros")
DB_USER = os.getenv("DB_USER", "motoros")
DB_PASSWORD = os.getenv("DB_PASSWORD", "motoros")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

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


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


def generate_vehicle_state(vin: str):
    is_ev = random.random() < 0.6
    return {
        "vehicle_vin": vin,
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "latitude": round(random.uniform(25.0, 48.0), 6),
        "longitude": round(random.uniform(-125.0, -70.0), 6),
        "speed_kmh": random.randint(0, 140),
        "soc_pct": round(random.uniform(10, 95), 2) if is_ev else None,
        "fuel_level_pct": None if is_ev else round(random.uniform(10, 95), 2),
        "engine_temp_c": round(random.uniform(35, 100), 1),
        "odometer_km": random.randint(5000, 120000),
        "engine_status": random.choice(["running", "idle", "off"]),
        "cell_voltage_min": round(random.uniform(3.18, 3.50), 2) if is_ev else None,
        "cell_voltage_max": round(random.uniform(3.98, 4.18), 2) if is_ev else None,
        "tire_pressure_kpa": {
            "front_left": round(random.uniform(225, 255), 1),
            "front_right": round(random.uniform(225, 255), 1),
            "rear_left": round(random.uniform(220, 250), 1),
            "rear_right": round(random.uniform(220, 250), 1),
        },
    }


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(1, 8), 2),
            "p95_latency_ms": round(random.uniform(8, 40), 2),
            "p99_latency_ms": round(random.uniform(40, 120), 2),
            "error_rate": round(random.uniform(0, 0.005), 4),
            "throughput_rps": round(random.uniform(500, 3000), 1),
            "db_connection_count": random.randint(5, 25),
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


@app.get("/vehicles/{vin}/state")
async def get_vehicle_state(vin: str):
    correlation_id = str(uuid.uuid4())
    logger.info("vehicle_state_query", correlation_id=correlation_id, vehicle_vin=vin)
    state = generate_vehicle_state(vin)
    logger.info("vehicle_state_returned", correlation_id=correlation_id, vehicle_vin=vin)
    return state


@app.get("/vehicles")
async def list_vehicles():
    correlation_id = str(uuid.uuid4())
    logger.info("vehicle_list_query", correlation_id=correlation_id)
    return {
        "vehicles": [{"vin": vin, "status": random.choice(["active", "idle", "maintenance"])} for vin in FAKE_VINS[:10]],
        "total": len(FAKE_VINS),
    }
