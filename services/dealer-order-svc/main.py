import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "dealer-order-svc")
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

DEALER_CODES = [f"DLR-{random.randint(1000, 9999)}" for _ in range(15)]
ORDER_STATUSES = ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


class OrderCreate(BaseModel):
    dealer_code: str
    vehicle_vin: str
    parts: list = []
    priority: str = "normal"


async def order_processor_task():
    """Simulates processing orders from queue."""
    await asyncio.sleep(6)
    while True:
        correlation_id = str(uuid.uuid4())
        dealer_code = random.choice(DEALER_CODES)
        logger.info("order_processing", correlation_id=correlation_id,
                    dealer_code=dealer_code,
                    order_id=f"ORD-{random.randint(100000, 999999)}",
                    status=random.choice(ORDER_STATUSES))
        await asyncio.sleep(random.uniform(5, 15))


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(10, 50), 2),
            "p95_latency_ms": round(random.uniform(50, 200), 2),
            "p99_latency_ms": round(random.uniform(200, 800), 2),
            "error_rate": round(random.uniform(0, 0.01), 4),
            "throughput_rps": round(random.uniform(50, 300), 1),
            "db_connection_count": random.randint(2, 8),
            "queue_depth": random.randint(0, 200),
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
    asyncio.create_task(order_processor_task())
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


@app.post("/orders", status_code=201)
async def create_order(order: OrderCreate):
    correlation_id = str(uuid.uuid4())
    order_id = f"ORD-{random.randint(100000, 999999)}"
    logger.info("order_created", correlation_id=correlation_id,
                dealer_code=order.dealer_code, order_id=order_id,
                vehicle_vin=order.vehicle_vin)
    return {"order_id": order_id, "status": "pending", "dealer_code": order.dealer_code}


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    correlation_id = str(uuid.uuid4())
    logger.info("order_query", correlation_id=correlation_id, order_id=order_id)
    return {
        "order_id": order_id,
        "dealer_code": random.choice(DEALER_CODES),
        "status": random.choice(ORDER_STATUSES),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": random.randint(1, 10),
        "total_amount": round(random.uniform(500, 50000), 2),
    }


@app.get("/dealers/{dealer_code}/orders")
async def list_dealer_orders(dealer_code: str):
    correlation_id = str(uuid.uuid4())
    logger.info("dealer_orders_query", correlation_id=correlation_id, dealer_code=dealer_code)
    orders = [
        {"order_id": f"ORD-{random.randint(100000, 999999)}", "status": random.choice(ORDER_STATUSES)}
        for _ in range(random.randint(3, 15))
    ]
    return {"dealer_code": dealer_code, "orders": orders, "total": len(orders)}
