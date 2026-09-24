"""
session_models.py - SQLAlchemy models for ScanSession (multi-document checkpoint visits).
One session = one traveler's complete checkpoint visit with 1+ document scans.
"""
from datetime import datetime
import uuid
from sqlalchemy import Column, String, DateTime, Integer, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from .database import Base


def generate_session_id() -> str:
    today_str = datetime.utcnow().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:8].upper()
    return f"SES-{today_str}-{short_uuid}"


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id = Column(String(64), primary_key=True, default=generate_session_id)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    officer_id = Column(String(64), default="OFFICER-4819", index=True)
    station_id = Column(String(128), default="Delhi IGI Airport (T3 Arrival)")
    status = Column(String(32), default="OPEN", index=True)  # OPEN, COMPLETE, ABORTED, DISCARDED
    documents_required = Column(Integer, default=3)

    # Lifecycle & Audit Attribution
    completed_at = Column(DateTime, nullable=True, index=True)
    decision = Column(String(64), nullable=True)  # APPROVED, FLAGGED, REJECTED, DETAINED, CLEARED, DISCARDED
    risk_score = Column(String(32), nullable=True)  # Float formatted or string score
    risk_tier = Column(String(32), nullable=True, index=True)  # LOW, MEDIUM, HIGH, CRITICAL
    document_types = Column(String(255), nullable=True)  # e.g. "passport, national_id"
    findings_summary = Column(Text, nullable=True)

    # Cross-document result (populated after report is generated)
    cross_document_report = Column(JSON, nullable=True)

    # Relationship: all scans linked to this session
    scans = relationship("SessionScanLink", back_populates="session", cascade="all, delete-orphan")


class SessionScanLink(Base):
    """Links a ScanSession to individual scan records (each document scan)."""
    __tablename__ = "session_scan_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("scan_sessions.id"), nullable=False, index=True)
    scan_id = Column(String(64), nullable=False, index=True)   # References ScanRecord.id
    document_type = Column(String(64), nullable=True)
    document_label = Column(String(128), nullable=True)       # e.g. "Passport", "National ID", "Driving License"
    holder_name = Column(String(255), nullable=True)
    document_number = Column(String(128), nullable=True)
    linked_at = Column(DateTime, default=datetime.utcnow)
    scan_payload = Column(JSON, nullable=True)                # Stores full individual scan report

    session = relationship("ScanSession", back_populates="scans")
