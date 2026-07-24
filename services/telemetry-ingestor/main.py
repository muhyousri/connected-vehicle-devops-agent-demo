import os
import sys
import uuid
import random
import asyncio
import time
import json
from datetime import datetime, timezone

import structlog
import boto3
import psycopg2
from fastapi import FastAPI, Request

# Configuration
SERVICE_NAME = os.getenv("SERVICE_NAME", "telemetry-ingestor")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "motoros")
DB_USER = os.getenv("DB_USER", "motoros")
DB_PASSWORD = os.getenv("DB_PASSWORD", "motoros")
KINESIS_STREAM = os.getenv("KINESIS_STREAM", "motoros-telemetry-stream")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(service=SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)

# Fake VIN generator
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


def generate_telemetry_record():
    is_ev = random.random() < 0.6  # 60% EV fleet
    rec = {
        "vehicle_vin": random.choice(FAKE_VINS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latitude": round(random.uniform(25.0, 48.0), 6),
        "longitude": round(random.uniform(-125.0, -70.0), 6),
        "speed_kmh": random.randint(0, 140),
        "soc_pct": round(random.uniform(8, 98), 2) if is_ev else None,
        "fuel_level_pct": None if is_ev else round(random.uniform(5, 95), 2),
        "cell_voltage_min": round(random.uniform(3.15, 3.55), 2) if is_ev else None,
        "cell_voltage_max": round(random.uniform(3.95, 4.20), 2) if is_ev else None,
        "tire_pressure_fl": round(random.uniform(225, 260), 1),
        "tire_pressure_fr": round(random.uniform(225, 260), 1),
        "tire_pressure_rl": round(random.uniform(220, 255), 1),
        "tire_pressure_rr": round(random.uniform(220, 255), 1),
        "ambient_temp_c": round(random.uniform(-5, 38), 1),
        "engine_temp_c": round(random.uniform(35, 105), 1),
        "odometer_km": random.randint(1000, 120000),
    }
    return rec


async def kinesis_reader_task():
    """Background task: reads from Kinesis every 10 seconds."""
    await asyncio.sleep(3)  # startup delay
    while True:
        try:
            correlation_id = str(uuid.uuid4())
            logger.info("kinesis_poll_start", correlation_id=correlation_id,
                        stream=KINESIS_STREAM)

            # Simulate Kinesis read (in demo, boto3 call may fail gracefully)
            try:
                client = boto3.client("kinesis", region_name=AWS_REGION)
                response = client.describe_stream(StreamName=KINESIS_STREAM)
                shard_count = len(response["StreamDescription"]["Shards"])
                logger.info("kinesis_stream_described", correlation_id=correlation_id,
                            shard_count=shard_count)
            except Exception as e:
                logger.warning("kinesis_read_simulated", correlation_id=correlation_id,
                               error=str(e), message="Falling back to synthetic data")

            # Generate and insert fake telemetry records
            records = [generate_telemetry_record() for _ in range(random.randint(5, 20))]
            conn = get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    for rec in records:
                        cur.execute(
                            """INSERT INTO telemetry_events
                               (vehicle_vin, event_timestamp, latitude, longitude,
                                speed_kmh, soc_pct, fuel_level_pct, cell_voltage_min,
                                cell_voltage_max, tire_pressure_fl, tire_pressure_fr,
                                tire_pressure_rl, tire_pressure_rr, ambient_temp_c,
                                engine_temp_c, odometer_km)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT DO NOTHING""",
                            (rec["vehicle_vin"], rec["timestamp"], rec["latitude"],
                             rec["longitude"], rec["speed_kmh"], rec["soc_pct"],
                             rec["fuel_level_pct"], rec["cell_voltage_min"],
                             rec["cell_voltage_max"], rec["tire_pressure_fl"],
                             rec["tire_pressure_fr"], rec["tire_pressure_rl"],
                             rec["tire_pressure_rr"], rec["ambient_temp_c"],
                             rec["engine_temp_c"], rec["odometer_km"])
                        )
                    conn.commit()
                    logger.info("telemetry_records_inserted", correlation_id=correlation_id,
                                record_count=len(records),
                                vehicle_vin=records[0]["vehicle_vin"])
                except Exception as e:
                    logger.error("db_insert_failed", correlation_id=correlation_id, error=str(e))
                    conn.rollback()
                finally:
                    conn.close()
            else:
                logger.warning("db_unavailable", correlation_id=correlation_id,
                               message="Skipping insert, no DB connection")

        except Exception as e:
            logger.error("kinesis_reader_error", error=str(e))

        await asyncio.sleep(10)


async def metrics_emitter_task():
    """Emit fake CloudWatch metrics every 15 seconds."""
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(2, 15), 2),
            "p95_latency_ms": round(random.uniform(15, 80), 2),
            "p99_latency_ms": round(random.uniform(80, 250), 2),
            "error_rate": round(random.uniform(0, 0.02), 4),
            "throughput_rps": round(random.uniform(100, 2000), 1),
            "db_connection_count": random.randint(2, 20),
            "queue_depth": random.randint(0, 500),
        }
        logger.info("metrics_emitted", **metrics, service=SERVICE_NAME)
        await asyncio.sleep(15)


async def db_keepalive_task():
    """Periodic DB ping to keep connections alive."""
    await asyncio.sleep(8)
    while True:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                conn.close()
                logger.debug("db_keepalive_ok")
            except Exception as e:
                logger.warning("db_keepalive_failed", error=str(e))
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup():
    logger.info("service_starting", service=SERVICE_NAME)
    asyncio.create_task(kinesis_reader_task())
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


@app.post("/ingest")
async def ingest_telemetry(request: Request):
    correlation_id = str(uuid.uuid4())
    logger.info("manual_ingest_request", correlation_id=correlation_id)
    records = [generate_telemetry_record() for _ in range(random.randint(1, 5))]
    return {"status": "accepted", "correlation_id": correlation_id, "record_count": len(records)}
