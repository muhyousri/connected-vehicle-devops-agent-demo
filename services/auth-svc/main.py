import os
import uuid
import random
import asyncio
import hashlib
import base64
from datetime import datetime, timezone, timedelta

import structlog
import psycopg2
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "auth-svc")
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

ROLES = ["admin", "fleet_manager", "dealer", "technician", "viewer"]


def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5
        )
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return None


def generate_fake_jwt():
    """Generate a fake JWT-like token for demo purposes."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
    payload_data = {
        "sub": str(uuid.uuid4()),
        "iss": "motoros-auth",
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "roles": random.sample(ROLES, random.randint(1, 3)),
    }
    payload = base64.urlsafe_b64encode(str(payload_data).encode()).decode().rstrip("=")
    sig = hashlib.sha256(f"{header}.{payload}".encode()).hexdigest()[:43]
    return f"{header}.{payload}.{sig}"


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenRefreshRequest(BaseModel):
    refresh_token: str


async def metrics_emitter_task():
    await asyncio.sleep(5)
    while True:
        metrics = {
            "p50_latency_ms": round(random.uniform(2, 10), 2),
            "p95_latency_ms": round(random.uniform(10, 40), 2),
            "p99_latency_ms": round(random.uniform(40, 100), 2),
            "error_rate": round(random.uniform(0, 0.02), 4),
            "throughput_rps": round(random.uniform(200, 1500), 1),
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


@app.post("/auth/login")
async def login(request: LoginRequest):
    correlation_id = str(uuid.uuid4())
    logger.info("login_attempt", correlation_id=correlation_id, username=request.username)

    # Simulate authentication (always succeeds for demo)
    access_token = generate_fake_jwt()
    refresh_token = str(uuid.uuid4())

    logger.info("login_success", correlation_id=correlation_id, username=request.username)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@app.post("/auth/refresh")
async def refresh_token(request: TokenRefreshRequest):
    correlation_id = str(uuid.uuid4())
    logger.info("token_refresh", correlation_id=correlation_id)
    access_token = generate_fake_jwt()
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@app.post("/auth/validate")
async def validate_token(request: Request):
    correlation_id = str(uuid.uuid4())
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("token_validation_failed", correlation_id=correlation_id, reason="missing_bearer")
        raise HTTPException(status_code=401, detail="Invalid token")

    logger.info("token_validated", correlation_id=correlation_id)
    return {
        "valid": True,
        "subject": str(uuid.uuid4()),
        "roles": random.sample(ROLES, random.randint(1, 3)),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=random.randint(10, 55))).isoformat(),
    }


@app.post("/auth/logout")
async def logout(request: Request):
    correlation_id = str(uuid.uuid4())
    logger.info("logout", correlation_id=correlation_id)
    return {"status": "logged_out"}
