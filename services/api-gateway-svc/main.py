import os
import uuid
import random
import asyncio
from datetime import datetime, timezone

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException

SERVICE_NAME = os.getenv("SERVICE_NAME", "api-gateway-svc")
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

# Simulated upstream service registry
UPSTREAM_SERVICES = {
    "vehicles": {"host": "vehicle-state-svc", "port": 8080, "status": "healthy"},
    "fleets": {"host": "fleet-registry-svc", "port": 8080, "status": "healthy"},
    "orders": {"host": "dealer-order-svc", "port": 8080, "status": "healthy"},
    "warranties": {"host": "warranty-claims-svc", "port": 8080, "status": "healthy"},
    "campaigns": {"host": "ota-campaign-svc", "port": 8080, "status": "healthy"},
    "firmware": {"host": "firmware-distribution-svc", "port": 8080, "status": "healthy"},
    "auth": {"host": "auth-svc", "port": 8080, "status": "healthy"},
    "notifications": {"host": "notification-svc", "port": 8080, "status": "healthy"},
    "audit": {"host": "audit-log-svc", "port": 8080, "status": "healthy"},
}


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


async def health_checker_task():
    """Periodically checks upstream service health."""
    await asyncio.sleep(5)
    while True:
        for svc_name, svc_info in UPSTREAM_SERVICES.items():
            # Simulate health check (mostly healthy, occasionally degraded)
            status = random.choices(
                ["healthy", "degraded", "unhealthy"],
                weights=[90, 8, 2]
            )[0]
            svc_info["status"] = status
            if status != "healthy":
                logger.warning("upstream_health_check", upstream=svc_name, status=status)
        await asyncio.sleep(15)


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(5, 20), 2),
            "p95_latency_ms": round(random.uniform(20, 100), 2),
            "p99_latency_ms": round(random.uniform(100, 500), 2),
            "error_rate": round(random.uniform(0, 0.01), 4),
            "throughput_rps": round(random.uniform(500, 5000), 1),
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
    asyncio.create_task(health_checker_task())
    asyncio.create_task(metrics_emitter_task())
    asyncio.create_task(db_keepalive_task())


@app.get("/health")
async def health():
    return {"status": "healthy", "service": SERVICE_NAME, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
async def ready():
    healthy_upstreams = sum(1 for s in UPSTREAM_SERVICES.values() if s["status"] == "healthy")
    total = len(UPSTREAM_SERVICES)
    if healthy_upstreams < total * 0.5:
        return {"status": "not_ready", "service": SERVICE_NAME,
                "reason": f"Only {healthy_upstreams}/{total} upstreams healthy"}
    return {"status": "ready", "service": SERVICE_NAME,
            "healthy_upstreams": healthy_upstreams, "total_upstreams": total}


@app.get("/gateway/services")
async def list_services():
    correlation_id = str(uuid.uuid4())
    logger.info("services_list", correlation_id=correlation_id)
    return {"services": UPSTREAM_SERVICES}


@app.get("/gateway/routes")
async def list_routes():
    routes = [
        {"path": "/api/v1/vehicles/**", "upstream": "vehicle-state-svc", "methods": ["GET"]},
        {"path": "/api/v1/fleets/**", "upstream": "fleet-registry-svc", "methods": ["GET", "POST", "PUT", "DELETE"]},
        {"path": "/api/v1/orders/**", "upstream": "dealer-order-svc", "methods": ["GET", "POST"]},
        {"path": "/api/v1/warranties/**", "upstream": "warranty-claims-svc", "methods": ["GET", "POST"]},
        {"path": "/api/v1/campaigns/**", "upstream": "ota-campaign-svc", "methods": ["GET", "POST"]},
        {"path": "/api/v1/firmware/**", "upstream": "firmware-distribution-svc", "methods": ["GET"]},
        {"path": "/api/v1/auth/**", "upstream": "auth-svc", "methods": ["POST"]},
        {"path": "/api/v1/notifications/**", "upstream": "notification-svc", "methods": ["POST", "GET"]},
        {"path": "/api/v1/audit/**", "upstream": "audit-log-svc", "methods": ["GET", "POST"]},
    ]
    return {"routes": routes, "total": len(routes)}


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_request(path: str, request: Request):
    correlation_id = str(uuid.uuid4())
    method = request.method
    prefix = path.split("/")[0] if "/" in path else path

    logger.info("request_routed", correlation_id=correlation_id,
                method=method, path=f"/api/v1/{path}", prefix=prefix)

    # Simulate routing latency
    latency_ms = random.uniform(5, 50)

    # Check if upstream is healthy
    svc = UPSTREAM_SERVICES.get(prefix)
    if svc and svc["status"] == "unhealthy":
        logger.error("upstream_unavailable", correlation_id=correlation_id,
                     upstream=prefix, status="unhealthy")
        raise HTTPException(status_code=503, detail=f"Upstream {prefix} is unavailable")

    return {
        "routed_to": svc["host"] if svc else "unknown",
        "path": f"/api/v1/{path}",
        "method": method,
        "correlation_id": correlation_id,
        "latency_ms": round(latency_ms, 2),
        "status": "proxied",
    }
