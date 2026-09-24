"""
screening_history.py - Append-Only Screening History Storage Engine.

Enforces strict append-only compliance for border screening records.
- Records are immutable once written (SQLAlchemy listeners reject UPDATE / DELETE).
- Corrections are stored as separate, linked records referencing original_screening_id.
- Fast repeat-identity lookups via indexed document_number and composite (name, dob).
- Stores SHA-256 digests of document imagery; raw images are never persisted here.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    event,
    select,
)
from sqlalchemy.orm import Session, relationship, backref

from backend.db.database import Base, engine

logger = logging.getLogger("sentinel.screening_history")

# Standard Outcomes
ALLOWED_OUTCOMES = {"VERIFIED", "TAMPERED", "EXPIRED", "SKIPPED", "UNKNOWN"}
ALLOWED_CHECK_RESULTS = {"PASSED", "FAILED", "NOT_EVALUATED"}


def generate_screening_id() -> str:
    """Generate unique sequential-like screening ID: SCR-YYYYMMDD-XXXXXX."""
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"SCR-{today_str}-{short_uuid}"


def mask_document_number(raw_num: str, doc_type: str = "") -> str:
    """
    Standardize and securely mask document numbers for PII-safe storage.
    - Aadhaar: XXXX XXXX 1107
    - Passport: AD*****43
    - PAN: ABCDE****F
    - Generic: keep first 2 and last 2 characters, masking middle with *
    """
    if not raw_num:
        return ""
    stripped = raw_num.strip()
    clean = stripped.replace(" ", "").replace("-", "")

    # Preserve already masked representations
    if "X" in clean.upper() or "*" in clean:
        return stripped

    doc_lower = (doc_type or "").lower()

    if "aadhaar" in doc_lower or (len(clean) == 12 and clean.isdigit()):
        return f"XXXX XXXX {clean[-4:]}"
    elif "pan" in doc_lower or (len(clean) == 10 and clean[:5].isalpha() and clean[5:9].isdigit()):
        return f"{clean[:5]}****{clean[-1]}"
    elif "passport" in doc_lower:
        if len(clean) >= 4:
            return f"{clean[:2]}{'*' * (len(clean) - 4)}{clean[-2:]}"
        return f"{clean[:1]}****"
    else:
        if len(clean) <= 4:
            return "****"
        return f"{clean[:2]}{'*' * (len(clean) - 4)}{clean[-2:]}"


def compute_sha256(data: bytes | str) -> str:
    """Compute SHA-256 digest of raw bytes or string payload."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class ScreeningHistoryRecord(Base):
    """
    Immutable screening history table.
    Guarantees full auditability of all border checks and manual officer corrections.
    """
    __tablename__ = "screening_history"

    # Core Identifiers
    screening_id = Column(String(64), primary_key=True, default=generate_screening_id)
    timestamp = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
        index=True,
    )
    officer_id = Column(String(64), nullable=False, index=True)

    # Document & Identity Attributes
    document_type = Column(String(64), nullable=False, index=True)
    document_number = Column(String(128), nullable=False)  # Masked representation
    name = Column(String(255), nullable=True)
    dob = Column(String(32), nullable=True)  # Format: YYYY-MM-DD or DD/MM/YYYY
    nationality = Column(String(32), nullable=True)  # ISO 3166-1 alpha-3 code (e.g. IND)

    # Outcome & Risk
    outcome = Column(String(32), nullable=False, default="UNKNOWN")  # VERIFIED, TAMPERED, etc.
    risk_score = Column(Float, nullable=False, default=0.0)

    # Granular Checks Breakdown: { "check_name": { "status": "PASSED|FAILED|NOT_EVALUATED", "reason": "..." } }
    checks = Column(JSON, nullable=False, default=dict)

    # Outcome Trigger Metadata
    producing_check = Column(String(128), nullable=True)
    producing_field = Column(String(128), nullable=True)

    # Linkage & Performance
    session_id = Column(String(64), nullable=True, index=True)
    image_hash = Column(String(64), nullable=True, index=True)  # SHA-256 (64 hex characters)
    processing_time_ms = Column(Float, nullable=False, default=0.0)

    # Immutable Correction Trail
    is_correction = Column(Boolean, nullable=False, default=False, index=True)
    original_screening_id = Column(
        String(64),
        ForeignKey("screening_history.screening_id"),
        nullable=True,
        index=True,
    )
    correction_reason = Column(Text, nullable=True)
    corrected_by = Column(String(64), nullable=True)

    # Relationships
    corrections = relationship(
        "ScreeningHistoryRecord",
        backref=backref("original_record", remote_side=[screening_id]),
        foreign_keys=[original_screening_id],
        order_by="ScreeningHistoryRecord.timestamp.asc()",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_screening_doc_num", "document_number"),
        Index("idx_screening_name_dob", "name", "dob"),
        Index("idx_screening_session", "session_id"),
        Index("idx_screening_img_hash", "image_hash"),
        Index("idx_screening_orig_id", "original_screening_id"),
    )

    def to_dict(self, include_corrections: bool = True) -> Dict[str, Any]:
        """Serialize record to dictionary matching schema specifications."""
        ts_str = self.timestamp.isoformat() if self.timestamp else None
        if ts_str and not ts_str.endswith("Z"):
            ts_str += "Z"

        data: Dict[str, Any] = {
            "screening_id": self.screening_id,
            "timestamp": ts_str,
            "officer_id": self.officer_id,
            "document_type": self.document_type,
            "document_number": self.document_number,
            "name": self.name,
            "dob": self.dob,
            "nationality": self.nationality,
            "outcome": self.outcome,
            "risk_score": round(float(self.risk_score), 2),
            "checks": self.checks or {},
            "outcome_trigger": {
                "producing_check": self.producing_check,
                "producing_field": self.producing_field,
            },
            "session_id": self.session_id,
            "image_hash": self.image_hash,
            "processing_time_ms": round(float(self.processing_time_ms), 2),
            "is_correction": bool(self.is_correction),
            "original_screening_id": self.original_screening_id,
            "correction_reason": self.correction_reason,
            "corrected_by": self.corrected_by,
        }

        data["corrections"] = []
        if include_corrections:
            try:
                if self.corrections:
                    data["corrections"] = [c.to_dict(include_corrections=False) for c in self.corrections]
            except Exception:
                pass

        return data


# Enforce strict append-only immutability at SQLAlchemy ORM layer
@event.listens_for(ScreeningHistoryRecord, "before_update")
def _guard_screening_history_no_update(mapper, connection, target):
    raise RuntimeError(
        f"ScreeningHistoryRecord '{target.screening_id}' is strictly append-only. "
        "Direct updates are prohibited. Use create_correction_record() to append a linked correction."
    )


@event.listens_for(ScreeningHistoryRecord, "before_delete")
def _guard_screening_history_no_delete(mapper, connection, target):
    raise RuntimeError(
        f"ScreeningHistoryRecord '{target.screening_id}' is strictly append-only. "
        "Deletions are prohibited by border audit compliance policies."
    )


# Auto-create table and indexes if not existing
Base.metadata.create_all(bind=engine, tables=[ScreeningHistoryRecord.__table__])


def create_screening_record(
    db: Session,
    *,
    officer_id: str,
    document_type: str,
    document_number: str,
    name: Optional[str] = None,
    dob: Optional[str] = None,
    nationality: Optional[str] = None,
    outcome: str = "UNKNOWN",
    risk_score: float = 0.0,
    checks: Optional[Dict[str, Dict[str, str]]] = None,
    producing_check: Optional[str] = None,
    producing_field: Optional[str] = None,
    session_id: Optional[str] = None,
    image_hash: Optional[str] = None,
    processing_time_ms: float = 0.0,
    screening_id: Optional[str] = None,
) -> ScreeningHistoryRecord:
    """
    Append a new primary screening record.
    Never mutates existing rows.
    """
    norm_outcome = outcome.upper() if outcome else "UNKNOWN"
    if norm_outcome not in ALLOWED_OUTCOMES:
        norm_outcome = "UNKNOWN"

    masked_doc_num = mask_document_number(document_number, document_type)

    # Validate / sanitize granular checks
    sanitized_checks: Dict[str, Dict[str, str]] = {}
    if checks:
        for chk_name, chk_val in checks.items():
            if isinstance(chk_val, dict):
                st = chk_val.get("status", "NOT_EVALUATED").upper()
                if st not in ALLOWED_CHECK_RESULTS:
                    st = "NOT_EVALUATED"
                rsn = str(chk_val.get("reason", ""))
                sanitized_checks[chk_name] = {"status": st, "reason": rsn}
            else:
                sanitized_checks[chk_name] = {"status": "NOT_EVALUATED", "reason": str(chk_val)}

    record = ScreeningHistoryRecord(
        screening_id=screening_id or generate_screening_id(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        officer_id=officer_id,
        document_type=document_type,
        document_number=masked_doc_num,
        name=name.strip() if name else None,
        dob=dob.strip() if dob else None,
        nationality=nationality.strip().upper() if nationality else None,
        outcome=norm_outcome,
        risk_score=float(risk_score),
        checks=sanitized_checks,
        producing_check=producing_check,
        producing_field=producing_field,
        session_id=session_id,
        image_hash=image_hash,
        processing_time_ms=float(processing_time_ms),
        is_correction=False,
        original_screening_id=None,
        correction_reason=None,
        corrected_by=None,
    )

    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"Screening record appended: {record.screening_id} (Outcome: {record.outcome}, Risk: {record.risk_score})")
    return record


def create_correction_record(
    db: Session,
    *,
    original_screening_id: str,
    corrected_by: str,
    correction_reason: str,
    new_outcome: str,
    new_risk_score: Optional[float] = None,
    new_checks: Optional[Dict[str, Dict[str, str]]] = None,
    producing_check: Optional[str] = None,
    producing_field: Optional[str] = None,
) -> ScreeningHistoryRecord:
    """
    Append an immutable correction record pointing to the original screening.
    The original decision remains unchanged and visible in history.
    """
    original = db.query(ScreeningHistoryRecord).filter(
        ScreeningHistoryRecord.screening_id == original_screening_id
    ).first()

    if not original:
        raise ValueError(f"Original screening record '{original_screening_id}' not found.")

    norm_outcome = new_outcome.upper() if new_outcome else original.outcome
    if norm_outcome not in ALLOWED_OUTCOMES:
        norm_outcome = "UNKNOWN"

    score = float(new_risk_score) if new_risk_score is not None else original.risk_score
    checks_dict = new_checks if new_checks is not None else (original.checks or {})

    correction = ScreeningHistoryRecord(
        screening_id=generate_screening_id(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        officer_id=corrected_by,
        document_type=original.document_type,
        document_number=original.document_number,
        name=original.name,
        dob=original.dob,
        nationality=original.nationality,
        outcome=norm_outcome,
        risk_score=score,
        checks=checks_dict,
        producing_check=producing_check or original.producing_check,
        producing_field=producing_field or original.producing_field,
        session_id=original.session_id,
        image_hash=original.image_hash,
        processing_time_ms=0.0,
        is_correction=True,
        original_screening_id=original.screening_id,
        correction_reason=correction_reason,
        corrected_by=corrected_by,
    )

    db.add(correction)
    db.commit()
    db.refresh(correction)
    logger.info(
        f"Correction record appended: {correction.screening_id} -> Original: {original.screening_id} "
        f"(New Outcome: {correction.outcome}, Corrected By: {corrected_by})"
    )
    return correction


def get_screening_record(
    db: Session,
    screening_id: str,
) -> Optional[ScreeningHistoryRecord]:
    """Retrieve a single screening record by ID."""
    return db.query(ScreeningHistoryRecord).filter(
        ScreeningHistoryRecord.screening_id == screening_id
    ).first()


def search_screening_history(
    db: Session,
    *,
    document_number: Optional[str] = None,
    name: Optional[str] = None,
    dob: Optional[str] = None,
    nationality: Optional[str] = None,
    outcome: Optional[str] = None,
    officer_id: Optional[str] = None,
    session_id: Optional[str] = None,
    image_hash: Optional[str] = None,
    start_time: Optional[datetime.datetime] = None,
    end_time: Optional[datetime.datetime] = None,
    include_corrections_only: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[ScreeningHistoryRecord], int]:
    """
    Search historical screening records with indexed filters.
    Returns (records, total_count).
    """
    q = db.query(ScreeningHistoryRecord)

    if document_number:
        # Match either exact masked string or contains digits
        masked_search = mask_document_number(document_number)
        q = q.filter(
            (ScreeningHistoryRecord.document_number == document_number) |
            (ScreeningHistoryRecord.document_number == masked_search) |
            (ScreeningHistoryRecord.document_number.like(f"%{document_number.strip()}%"))
        )

    if name and dob:
        # Uses composite index idx_screening_name_dob
        q = q.filter(
            ScreeningHistoryRecord.name.ilike(f"%{name.strip()}%"),
            ScreeningHistoryRecord.dob == dob.strip(),
        )
    elif name:
        q = q.filter(ScreeningHistoryRecord.name.ilike(f"%{name.strip()}%"))
    elif dob:
        q = q.filter(ScreeningHistoryRecord.dob == dob.strip())

    if nationality:
        q = q.filter(ScreeningHistoryRecord.nationality == nationality.strip().upper())

    if outcome:
        q = q.filter(ScreeningHistoryRecord.outcome == outcome.strip().upper())

    if officer_id:
        q = q.filter(ScreeningHistoryRecord.officer_id == officer_id.strip())

    if session_id:
        q = q.filter(ScreeningHistoryRecord.session_id == session_id.strip())

    if image_hash:
        q = q.filter(ScreeningHistoryRecord.image_hash == image_hash.strip().lower())

    if start_time:
        q = q.filter(ScreeningHistoryRecord.timestamp >= start_time)

    if end_time:
        q = q.filter(ScreeningHistoryRecord.timestamp <= end_time)

    if include_corrections_only is True:
        q = q.filter(ScreeningHistoryRecord.is_correction == True)
    elif include_corrections_only is False:
        q = q.filter(ScreeningHistoryRecord.is_correction == False)

    total_count = q.count()
    records = q.order_by(ScreeningHistoryRecord.timestamp.desc()).offset(offset).limit(limit).all()
    return records, total_count


def check_repeat_identities(
    db: Session,
    *,
    name: Optional[str] = None,
    dob: Optional[str] = None,
    document_number: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Fast repeat-identity lookup leveraging idx_screening_doc_num and idx_screening_name_dob.
    Identifies:
    1. Past crossings by the same individual (name + DOB match).
    2. Document reuse anomalies (same document number presented under different names).
    """
    results: Dict[str, Any] = {
        "identity_matches": [],
        "document_matches": [],
        "anomalies_detected": [],
    }

    # 1. Identity lookup via composite index (name + DOB)
    if name and dob:
        identity_records = db.query(ScreeningHistoryRecord).filter(
            ScreeningHistoryRecord.name.ilike(f"%{name.strip()}%"),
            ScreeningHistoryRecord.dob == dob.strip(),
        ).order_by(ScreeningHistoryRecord.timestamp.desc()).limit(limit).all()

        results["identity_matches"] = [r.to_dict(include_corrections=False) for r in identity_records]

    # 2. Document lookup via document_number index
    if document_number:
        masked_search = mask_document_number(document_number)
        doc_records = db.query(ScreeningHistoryRecord).filter(
            (ScreeningHistoryRecord.document_number == document_number) |
            (ScreeningHistoryRecord.document_number == masked_search) |
            (ScreeningHistoryRecord.document_number.like(f"%{document_number.strip()}%"))
        ).order_by(ScreeningHistoryRecord.timestamp.desc()).limit(limit).all()

        results["document_matches"] = [r.to_dict(include_corrections=False) for r in doc_records]

        # Check for identity anomalies: same document number used with different name or DOB
        if name:
            norm_name = name.strip().lower()
            for rec in doc_records:
                if rec.name and rec.name.strip().lower() != norm_name:
                    results["anomalies_detected"].append({
                        "anomaly_type": "DOCUMENT_REUSE_DIFFERENT_NAME",
                        "screening_id": rec.screening_id,
                        "stored_name": rec.name,
                        "queried_name": name,
                        "timestamp": rec.timestamp.isoformat() + "Z" if rec.timestamp else None,
                    })

    return results
