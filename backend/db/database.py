"""
database.py - SQLAlchemy database configuration.
Defaults to local SQLite file for development, configurable to PostgreSQL via DATABASE_URL.
"""
import json
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from ..utils.serialization import NumpySafeEncoder, to_json_safe

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)

DEFAULT_SQLITE_URL = f"sqlite:///{os.path.join(DB_DIR, 'sentinel.db')}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

# SQLite requires check_same_thread=False for FastAPI concurrency
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}


def _safe_json_serializer(obj):
    return json.dumps(to_json_safe(obj), cls=NumpySafeEncoder)


engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    json_serializer=_safe_json_serializer,
    echo=False,
    future=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates all database tables and ensures schema migrations."""
    from . import models  # noqa: F401
    from . import session_models  # noqa: F401 — registers ScanSession & SessionScanLink
    Base.metadata.create_all(bind=engine)

    # Safe column additions for existing SQLite database
    with engine.connect() as conn:
        for col_name, col_type in [
            ("must_change_password", "BOOLEAN DEFAULT 0"),
            ("active", "BOOLEAN DEFAULT 1"),
            ("last_login", "DATETIME")
        ]:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            except Exception:
                pass

        for col_name, col_type in [
            ("completed_at", "DATETIME"),
            ("decision", "VARCHAR(64)"),
            ("risk_score", "VARCHAR(32)"),
            ("risk_tier", "VARCHAR(32)"),
            ("document_types", "VARCHAR(255)"),
            ("findings_summary", "TEXT")
        ]:
            try:
                conn.execute(text(f"ALTER TABLE scan_sessions ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            except Exception:
                pass

