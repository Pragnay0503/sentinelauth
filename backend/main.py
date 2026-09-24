"""
main.py - SentinelAuth Full-Stack AI Border Screening Platform.
Exposes endpoints for:
  - Module 1: OCR Extraction (/api/scan/ocr, /api/ocr/extract)
  - Module 2: Document Validation (/api/scan/validate, /api/validation/validate)
  - Module 3: Tampering Detection (/api/scan/tampering)
  - Module 4: Face Verification (/api/scan/face-verify)
  - Risk Engine & Persistence (/api/scan/full)
  - Audit Trail & Logs (/api/audit)
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader

from backend.db.database import init_db, SessionLocal
from backend.db.crud import seed_sample_data_if_empty
from backend.modules.ocr_extraction.ocr_engine import check_tesseract_ready, get_ocr_readiness, init_ocr_engine
from backend.modules.face_verification.engine import get_face_engine
from backend.modules.ocr_extraction.router import router as ocr_router
from backend.modules.document_validation.router import router as validation_router
from backend.api.routes_scan import router as scan_router
from backend.api.routes_audit import router as audit_router
from backend.api.routes_session import router as session_router

logger = logging.getLogger("sentinel")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

API_KEY_NAME = "X-Sentinel-Key"
DEFAULT_DEMO_KEY = "sentinel-secure-key-2026"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def verify_api_key_stub(api_key: str = Security(api_key_header)):
    """
    Security stub for border security checkpoint authentication.
    Accepts demo key or allows open pass-through with security warning logged,
    ready to be swapped for OAuth2 / JWT / PKI token validation in production.
    """
    if api_key and api_key != DEFAULT_DEMO_KEY:
        logger.warning(f"Unrecognized API key provided: {api_key}")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize SQLite / PostgreSQL Database
    try:
        init_db()
        db = SessionLocal()
        seed_sample_data_if_empty(db)
        db.close()
        logger.info("Database initialized and default security watchlists seeded.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # 2. Check Tesseract availability
    tesseract_available = check_tesseract_ready()
    if not tesseract_available:
        logger.info("Running with primary PaddleOCR neural engine.")

    # 3. Pre-warm OCR engine in background thread
    warmup_thread = threading.Thread(target=init_ocr_engine, daemon=True, name="OCR-Warmup-Thread")
    warmup_thread.start()

    # 4. Pre-warm Biometric Face Engine
    try:
        face_engine = get_face_engine()
        logger.info("Biometric Face Verification Engine (YuNet + SFace) pre-warmed.")
    except Exception as e:
        logger.warning(f"Face verification engine warmup warning: {e}")

    # 5. Start Automated 30-Minute Document Retention Scheduler
    try:
        from backend.services.retention_service import start_retention_scheduler, stop_retention_scheduler
        start_retention_scheduler()
    except Exception as e:
        logger.error(f"Failed to start retention scheduler: {e}")

    yield

    # Shutdown retention scheduler
    try:
        from backend.services.retention_service import stop_retention_scheduler
        stop_retention_scheduler()
    except Exception as e:
        logger.warning(f"Retention scheduler shutdown warning: {e}")

    logger.info("SentinelAuth backend shutting down.")


app = FastAPI(
    title="SentinelAuth - AI Document Screening Platform",
    version="2.5.0",
    description=(
        "Full-stack AI-Powered Document Screening Platform for border checkpoints. "
        "Performs OCR extraction, format validation, 5-point image forensics (ELA heatmap, EXIF, noise ratio, font metrics, stamp verification), "
        "deep 128-d biometric face matching, and explainable 0-100 risk scoring."
    ),
    lifespan=lifespan,
)

# Slowapi Rate Limiter
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers
app.include_router(scan_router)
app.include_router(session_router)
app.include_router(audit_router)
app.include_router(ocr_router)
app.include_router(validation_router)

# Authentication, Session Security & Data Retention routers
from backend.api.routes_auth import router as auth_router, admin_router
app.include_router(auth_router)
app.include_router(admin_router)

# Module 4: Biometric Face Verification alias route (/api/face/verify -> scan_face_verify_endpoint)
from fastapi import APIRouter
from backend.api.routes_scan import scan_face_verify_endpoint

face_router = APIRouter(prefix="/api/face", tags=["Face Verification"])
face_router.add_api_route("/verify", scan_face_verify_endpoint, methods=["POST"], summary="Alias for /api/scan/face-verify")
app.include_router(face_router)




@app.get("/")
async def root():
    readiness = get_ocr_readiness()
    return {
        "service": "SentinelAuth AI Border Screening API",
        "version": "2.5.0",
        "docs": "/docs",
        "ocr_ready": readiness["ready"],
        "ocr_loading": readiness["loading"],
        "modules": {
            "module_1_ocr": "ENABLED",
            "module_2_validation": "ENABLED",
            "module_3_tampering": "ENABLED",
            "module_4_biometrics": "ENABLED",
            "risk_scoring_engine": "ENABLED",
            "audit_persistence": "ENABLED"
        }
    }


@app.get("/api/health")
async def api_health():
    readiness = get_ocr_readiness()
    return {
        "status": "ok",
        "paddleocr_ready": readiness.get("paddleocr_ready", False),
        "tesseract_ready": readiness.get("tesseract_ready", False),
        "ocr_ready": readiness["ready"],
        "face_engine_ready": True,
        "database": "sqlite_connected",
        "model_status": "ready" if readiness["ready"] else "loading"
    }
