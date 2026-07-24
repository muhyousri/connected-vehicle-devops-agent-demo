import os
import sys
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException

SERVICE_NAME = os.getenv("SERVICE_NAME", "firmware-distribution-svc")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "motoros")
DB_USER = os.getenv("DB_USER", "motoros")
DB_PASSWORD = os.getenv("DB_PASSWORD", "motoros")
FORCE_CRASH = os.getenv("FORCE_CRASH", "false").lower() == "true"

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(service=SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)

FIRMWARE_VERSIONS = [
    {"version": "TCU-4.2.0", "ecu": "TCU", "size_mb": 85, "checksum": "sha256:a4f2c8e91b3d7056"},
    {"version": "TCU-4.3.0", "ecu": "TCU", "size_mb": 92, "checksum": "sha256:b7d1f5a230e84c19"},
    {"version": "IVI-3.1.4", "ecu": "IVI", "size_mb": 1240, "checksum": "sha256:c9e3a7b5d4f20816"},
    {"version": "BMS-2.8.1", "ecu": "BMS", "size_mb": 48, "checksum": "sha256:d2f8c4e7a1b63095"},
    {"version": "ADAS-1.5.0", "ecu": "ADAS", "size_mb": 520, "checksum": "sha256:e5a1d9c8b3f74021"},
    {"version": "VCU-2.4.0", "ecu": "VCU", "size_mb": 64, "checksum": "sha256:f8b2e6d4c5a19073"},
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


async def force_crash_task():
    """If FORCE_CRASH is set, exit after 5 seconds (for chaos testing)."""
    if FORCE_CRASH:
        logger.warning("force_crash_enabled", message="Service will crash in 5 seconds")
        await asyncio.sleep(5)
        logger.error("force_crash_triggered", message="Simulated crash for chaos testing")
        sys.exit(1)


async def distribution_monitor_task():
    """Simulates firmware distribution progress."""
    await asyncio.sleep(6)
    while True:
        fw = random.choice(FIRMWARE_VERSIONS)
        logger.info("firmware_distribution_progress",
                    firmware_version=fw["version"],
                    vehicles_downloading=random.randint(0, 200),
                    vehicles_installing=random.randint(0, 50),
                    vehicles_completed=random.randint(100, 5000),
                    bandwidth_mbps=round(random.uniform(50, 500), 1))
        await asyncio.sleep(10)


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(20, 80), 2),
            "p95_latency_ms": round(random.uniform(80, 300), 2),
            "p99_latency_ms": round(random.uniform(300, 1000), 2),
            "error_rate": round(random.uniform(0, 0.015), 4),
            "throughput_rps": round(random.uniform(10, 100), 1),
            "db_connection_count": random.randint(1, 6),
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
    logger.info("service_starting", service=SERVICE_NAME, force_crash=FORCE_CRASH)
    asyncio.create_task(force_crash_task())
    asyncio.create_task(distribution_monitor_task())
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


@app.get("/firmware")
async def list_firmware():
    correlation_id = str(uuid.uuid4())
    logger.info("firmware_list_query", correlation_id=correlation_id)
    return {"firmware": FIRMWARE_VERSIONS, "total": len(FIRMWARE_VERSIONS)}


@app.get("/firmware/{version}/download")
async def download_firmware(version: str):
    correlation_id = str(uuid.uuid4())
    fw = next((f for f in FIRMWARE_VERSIONS if f["version"] == version), None)
    if not fw:
        raise HTTPException(status_code=404, detail="Firmware version not found")
    logger.info("firmware_download_initiated", correlation_id=correlation_id,
                firmware_version=version, size_mb=fw["size_mb"])
    return {
        "version": version,
        "download_url": f"https://firmware.motoros.internal/packages/{version}/firmware.bin",
        "size_mb": fw["size_mb"],
        "checksum": fw["checksum"],
        "expires_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/firmware/{version}/status")
async def firmware_distribution_status(version: str):
    correlation_id = str(uuid.uuid4())
    logger.info("firmware_status_query", correlation_id=correlation_id, firmware_version=version)
    return {
        "version": version,
        "total_vehicles_targeted": random.randint(500, 10000),
        "downloaded": random.randint(200, 8000),
        "installed": random.randint(100, 7000),
        "failed": random.randint(0, 100),
        "pending": random.randint(0, 3000),
    }
