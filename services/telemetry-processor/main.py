import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request

SERVICE_NAME = os.getenv("SERVICE_NAME", "telemetry-processor")
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


async def process_telemetry_task():
    """Background task: processes telemetry events and updates vehicle state."""
    await asyncio.sleep(4)
    while True:
        try:
            correlation_id = str(uuid.uuid4())
            vehicle_vin = random.choice(FAKE_VINS)
            batch_size = random.randint(10, 50)

            logger.info("processing_batch", correlation_id=correlation_id,
                        vehicle_vin=vehicle_vin, batch_size=batch_size)

            conn = get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    # Simulate reading unprocessed events
                    cur.execute("SELECT 1")
                    conn.commit()
                    logger.info("batch_processed", correlation_id=correlation_id,
                                vehicle_vin=vehicle_vin, events_processed=batch_size,
                                processing_time_ms=round(random.uniform(20, 200), 2))
                except Exception as e:
                    logger.error("processing_failed", correlation_id=correlation_id, error=str(e))
                    conn.rollback()
                finally:
                    conn.close()

        except Exception as e:
            logger.error("process_task_error", error=str(e))

        await asyncio.sleep(8)


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(5, 30), 2),
            "p95_latency_ms": round(random.uniform(30, 150), 2),
            "p99_latency_ms": round(random.uniform(150, 500), 2),
            "error_rate": round(random.uniform(0, 0.01), 4),
            "throughput_rps": round(random.uniform(200, 5000), 1),
            "db_connection_count": random.randint(3, 15),
            "queue_depth": random.randint(0, 1000),
        }
        logger.info("metrics_emitted", **metrics)
        await asyncio.sleep(15)


async def db_keepalive_task():
    await asyncio.sleep(10)
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
    asyncio.create_task(process_telemetry_task())
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


@app.get("/stats")
async def stats():
    return {
        "service": SERVICE_NAME,
        "events_processed_total": random.randint(10000, 500000),
        "avg_processing_time_ms": round(random.uniform(15, 80), 2),
        "active_vehicles": random.randint(50, 500),
    }
