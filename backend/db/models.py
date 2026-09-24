"""
models.py - SQLAlchemy database models for SentinelAuth.
Tracks scan records, tamper forensic outputs, biometric match history, and blacklists.
"""
from datetime import datetime
import uuid
from sqlalchemy import (
    Column,
    String,
    Float,
    Boolean,
    DateTime,
    Integer,
    Text,
    JSON,
    ForeignKey
)
from sqlalchemy.orm import relationship
from .database import Base


def generate_scan_id() -> str:
    today_str = datetime.utcnow().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"SCAN-{today_str}-{short_uuid}"


class ScanRecord(Base):
    __tablename__ = "scan_records"

    id = Column(String(64), primary_key=True, default=generate_scan_id)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    document_type = Column(String(64), nullable=False, index=True)
    holder_name = Column(String(255), nullable=True, index=True)
    document_number = Column(String(128), nullable=True, index=True)
    
    # Scoring & Risk
    risk_score = Column(Float, nullable=False, default=0.0)
    risk_tier = Column(String(32), nullable=False, default="LOW", index=True)  # LOW, MEDIUM, HIGH, CRITICAL
    status = Column(String(32), nullable=False, default="PASSED", index=True)  # PASSED, FLAGGED, REJECTED
    
    # Sub-module metrics
    validation_passed = Column(Boolean, default=True)
    tampering_score = Column(Float, default=0.0)
    face_match_confidence = Column(Float, nullable=True)
    
    # Audit attribution
    officer_id = Column(String(64), default="OFFICER-4819", index=True)
    checkpoint = Column(String(128), default="Delhi IGI Airport (T3 Arrival)")
    
    # Complete JSON inspection result
    payload = Column(JSON, nullable=True)
    document_image_path = Column(String(512), nullable=True)

    # Relationship to audit action log
    actions = relationship("AuditLog", back_populates="scan", cascade="all, delete-orphan")


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_number = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    category = Column(String(64), default="FRAUD", index=True)  # TERRORISM, INTERPOL, FRAUD, STOLEN_DOC
    reason = Column(String(512), nullable=False)
    issuing_country = Column(String(64), default="IND")
    priority = Column(String(32), default="HIGH")  # MEDIUM, HIGH, CRITICAL
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(64), ForeignKey("scan_records.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    officer_id = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)  # CREATED, OVERRIDE, NOTE, EXPORT
    details = Column(Text, nullable=True)

    scan = relationship("ScanRecord", back_populates="actions")


class DocumentFile(Base):
    """
    Dedicated table tracking every uploaded/encrypted document image file on disk.
    Enforces a strict 30-minute data retention policy:
    - Files older than 30 minutes are purged from disk by the background retention job.
    - Rows are marked deleted=True as a tombstone record for compliance audit without retaining image bytes.
    """
    __tablename__ = "document_files"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_path = Column(String(512), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    session_id = Column(String(64), nullable=True, index=True)
    scan_id = Column(String(64), nullable=True, index=True)
    deleted = Column(Boolean, default=False, index=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class User(Base):
    """
    Authenticated Border Checkpoint Officers & System Administrators.
    Stores password hash (bcrypt), assigned badge, station, and security role.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    badge_id = Column(String(64), unique=True, index=True, nullable=False)
    officer_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(32), default="officer", nullable=False)  # admin, supervisor, officer
    station_id = Column(String(64), default="hyderabad-rgia")
    must_change_password = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RevokedToken(Base):
    """
    Server-side token blocklist for immediate session revocation upon logout.
    Prevents token replay attacks even if short-lived JWTs were captured.
    """
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    token_type = Column(String(16), default="access")  # access or refresh
    revoked_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, index=True, nullable=False)

