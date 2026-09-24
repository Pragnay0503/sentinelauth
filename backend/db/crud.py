"""
crud.py - Database operations for scans, audit logs, watchlists, document files, and user auth.
"""
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple
import bcrypt
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .models import ScanRecord, AuditLog, WatchlistEntry, DocumentFile, User, RevokedToken
from ..utils.serialization import to_json_safe

logger = logging.getLogger(__name__)



def create_scan_record(
    db: Session,
    document_type: str,
    holder_name: Optional[str],
    document_number: Optional[str],
    risk_score: float,
    risk_tier: str,
    status: str,
    validation_passed: bool,
    tampering_score: float,
    face_match_confidence: Optional[float],
    officer_id: str,
    checkpoint: str,
    payload: Dict[str, Any],
    document_image_path: Optional[str] = None,
    scan_id: Optional[str] = None,
) -> ScanRecord:
    safe_payload = to_json_safe(payload)
    init_kwargs: Dict[str, Any] = {
        "document_type": str(document_type),
        "holder_name": str(holder_name) if holder_name is not None else None,
        "document_number": str(document_number) if document_number is not None else None,
        "risk_score": float(risk_score),
        "risk_tier": str(risk_tier),
        "status": str(status),
        "validation_passed": bool(validation_passed),
        "tampering_score": float(tampering_score),
        "face_match_confidence": float(face_match_confidence) if face_match_confidence is not None else None,
        "officer_id": str(officer_id),
        "checkpoint": str(checkpoint),
        "payload": safe_payload,
        "document_image_path": document_image_path,
    }
    if scan_id:
        init_kwargs["id"] = scan_id

    record = ScanRecord(**init_kwargs)
    db.add(record)
    db.commit()
    db.refresh(record)

    # Automatically create the initial audit event
    log_event = AuditLog(
        scan_id=record.id,
        officer_id=officer_id,
        action="SCREENING_PROCESSED",
        details=f"Document screened: {document_type} (Risk: {risk_score:.1f}, Tier: {risk_tier})"
    )
    db.add(log_event)
    db.commit()

    return record


def get_scan_by_id(db: Session, scan_id: str) -> Optional[ScanRecord]:
    return db.query(ScanRecord).filter(ScanRecord.id == scan_id).first()


def search_scans(
    db: Session,
    query: Optional[str] = None,
    risk_tier: Optional[str] = None,
    document_type: Optional[str] = None,
    flagged_only: bool = False,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[ScanRecord], int]:
    q = db.query(ScanRecord)

    if query:
        search_pattern = f"%{query.strip()}%"
        q = q.filter(
            or_(
                ScanRecord.holder_name.ilike(search_pattern),
                ScanRecord.document_number.ilike(search_pattern),
                ScanRecord.id.ilike(search_pattern),
                ScanRecord.officer_id.ilike(search_pattern),
            )
        )

    if risk_tier and risk_tier.upper() != "ALL":
        q = q.filter(ScanRecord.risk_tier == risk_tier.upper())

    if document_type and document_type.upper() != "ALL":
        q = q.filter(ScanRecord.document_type.ilike(f"%{document_type}%"))

    if flagged_only:
        q = q.filter(ScanRecord.risk_tier.in_(["HIGH", "CRITICAL"]))

    if start_date:
        q = q.filter(ScanRecord.timestamp >= start_date)
    if end_date:
        q = q.filter(ScanRecord.timestamp <= end_date)

    total = q.count()
    items = q.order_by(ScanRecord.timestamp.desc()).offset(skip).limit(limit).all()
    return items, total



def get_dashboard_stats(db: Session) -> Dict[str, Any]:
    total_scans = db.query(func.count(ScanRecord.id)).scalar() or 0
    flagged_count = db.query(func.count(ScanRecord.id)).filter(
        ScanRecord.risk_tier.in_(["HIGH", "CRITICAL"])
    ).scalar() or 0
    passed_count = db.query(func.count(ScanRecord.id)).filter(
        ScanRecord.risk_tier == "LOW"
    ).scalar() or 0
    avg_risk = db.query(func.avg(ScanRecord.risk_score)).scalar() or 0.0

    # Risk tiers breakdown
    tiers = {
        "LOW": db.query(func.count(ScanRecord.id)).filter(ScanRecord.risk_tier == "LOW").scalar() or 0,
        "MEDIUM": db.query(func.count(ScanRecord.id)).filter(ScanRecord.risk_tier == "MEDIUM").scalar() or 0,
        "HIGH": db.query(func.count(ScanRecord.id)).filter(ScanRecord.risk_tier == "HIGH").scalar() or 0,
        "CRITICAL": db.query(func.count(ScanRecord.id)).filter(ScanRecord.risk_tier == "CRITICAL").scalar() or 0,
    }

    return {
        "total_scans": total_scans,
        "flagged_scans": flagged_count,
        "passed_scans": passed_count,
        "avg_risk_score": round(float(avg_risk), 1),
        "pass_rate_pct": round((passed_count / total_scans * 100), 1) if total_scans > 0 else 100.0,
        "tiers_breakdown": tiers,
    }


def seed_sample_data_if_empty(db: Session):
    """Seed initial watchlist and demo scan records if database is fresh."""
    if db.query(WatchlistEntry).count() == 0:
        initial_watchlist = [
            WatchlistEntry(
                document_number="M4820193",
                name="VIKRAM SHARMA",
                category="STOLEN_PASSPORT",
                reason="Interpol Stolen & Lost Travel Documents (SLTD) database match",
                issuing_country="IND",
                priority="CRITICAL"
            ),
            WatchlistEntry(
                document_number="K7401928",
                name="CARLOS MENDOZA",
                category="FRAUD",
                reason="Multiple forged visa attempts flagged across SAARC checkpoints",
                issuing_country="MEX",
                priority="HIGH"
            ),
            WatchlistEntry(
                document_number="P9023411",
                name="TARIQ AHMED",
                category="TERRORISM",
                reason="Intelligence alert #NTAC-2026-491",
                issuing_country="PAK",
                priority="CRITICAL"
            ),
            WatchlistEntry(
                document_number="4838 0779 9767",
                name="SAMPLE WATCHLIST TEST",
                category="TEST_ENTRY",
                reason="Demonstration watchlist test entry",
                issuing_country="IND",
                priority="MEDIUM"
            )
        ]
        db.add_all(initial_watchlist)
        db.commit()

    # Bootstrap initial admin account if users table is empty
    if db.query(User).count() == 0:
        from ..services.auth_service import generate_temporary_password
        admin_temp_pw = generate_temporary_password(12)
        admin_user = User(
            username="admin",
            badge_id="ADM-ROOT-001",
            officer_name="System Administrator",
            hashed_password=hash_password(admin_temp_pw),
            role="admin",
            station_id="hyderabad-rgia",
            must_change_password=True,
            active=True,
            created_at=datetime.utcnow()
        )
        db.add(admin_user)

        # Demo officer with a known password for evaluation — credentials are in README.md
        _DEMO_OFFICER_PASSWORD = "Demo@SentinelSSB1"
        demo_officer = User(
            username="demo_officer",
            badge_id="SSB-HYD-0001",
            officer_name="Demo Officer",
            hashed_password=hash_password(_DEMO_OFFICER_PASSWORD),
            role="officer",
            station_id="hyderabad-rgia",
            must_change_password=False,
            active=True,
            created_at=datetime.utcnow()
        )
        db.add(demo_officer)
        db.commit()

        border = "=" * 70
        print("\n" + border)
        print("[SENTINELAUTH BOOTSTRAP] Initial Admin Account Created")
        print(f"Username: {admin_user.username}")
        print(f"Badge ID: {admin_user.badge_id}")
        print(f"Temporary Password: {admin_temp_pw}")
        print("NOTICE: This temporary password is only displayed once to the console.")
        print("You must log in and change your password before accessing the system.")
        print("-" * 70)
        print("[SENTINELAUTH BOOTSTRAP] Demo Officer Account Created")
        print(f"Username: {demo_officer.username}  |  Badge: {demo_officer.badge_id}")
        print("Password: See README.md (Demo Credentials section)")
        print(border + "\n")
        logger.info(f"[BOOTSTRAP] Initial admin '{admin_user.username}' created with random temporary password.")
        logger.info(f"[BOOTSTRAP] Demo officer '{demo_officer.username}' seeded for evaluation.")




def check_scan_history(
    db: Session,
    document_number: Optional[str],
    holder_name: Optional[str],
    current_fields: Dict[str, Any],
    current_scan_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Cross-scan historical identity check:
    Searches past scan records by document number or fuzzy holder name (>= 85%).
    Compares stable fields (DOB, Nationality, Gender) across scan history.
    """
    import difflib
    from ..modules.document_validation.mrz_cross_validator import (
        _normalize_date_iso,
        _normalize_gender,
        _normalize_string,
    )

    clean_doc_num = re_sub_num(document_number) if document_number else None
    clean_holder = _normalize_string(holder_name) if holder_name else None

    # 1. Query past scan records (excluding current scan)
    query = db.query(ScanRecord)
    if current_scan_id:
        query = query.filter(ScanRecord.id != current_scan_id)

    candidates: List[ScanRecord] = []
    if clean_doc_num:
        # Match by exact or normalized doc number
        by_num = query.filter(ScanRecord.document_number.ilike(f"%{clean_doc_num}%")).all()
        candidates.extend(by_num)

    if clean_holder and len(clean_holder) >= 4:
        # Check recent scans for fuzzy holder name match (>= 85%)
        recent_scans = query.order_by(ScanRecord.timestamp.desc()).limit(150).all()
        for rec in recent_scans:
            if rec.id not in [c.id for c in candidates] and rec.holder_name:
                rec_name_norm = _normalize_string(rec.holder_name)
                ratio = difflib.SequenceMatcher(None, clean_holder, rec_name_norm).ratio()
                if ratio >= 0.85:
                    candidates.append(rec)

    if not candidates:
        return {
            "has_historical_match": False,
            "mismatches": [],
            "message": "No historical screening records found for this identity."
        }

    # Sort candidates by newest first
    candidates.sort(key=lambda r: r.timestamp or datetime.min, reverse=True)
    matched_record = candidates[0]

    # Extract previous fields from payload
    prev_payload = matched_record.payload or {}
    prev_ocr = prev_payload.get("ocr", {})
    prev_extracted = prev_ocr.get("extracted_fields", {})
    prev_visual = prev_ocr.get("visual_fields", {})

    def get_field_val(fields_container: Dict[str, Any], *keys: str) -> Optional[str]:
        for k in keys:
            if k in fields_container:
                v = fields_container[k]
                if isinstance(v, dict) and "value" in v:
                    return str(v["value"]).strip()
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if hasattr(v, "value"):
                    return str(v.value).strip()
        return None

    prev_fields_flat: Dict[str, str] = {}
    for k, v in {**prev_extracted, **prev_visual}.items():
        val = v.get("value") if isinstance(v, dict) else (v.value if hasattr(v, "value") else str(v))
        if val:
            prev_fields_flat[k] = str(val).strip()

    mismatches: List[Dict[str, Any]] = []
    prev_date_str = matched_record.timestamp.strftime("%Y-%m-%d") if matched_record.timestamp else "a prior screening"
    ref_doc = matched_record.document_number or document_number or "document"

    # 1. Compare Date of Birth
    cur_dob = get_field_val(current_fields, "date_of_birth", "dob", "birth_date")
    prev_dob = get_field_val(prev_fields_flat, "date_of_birth", "dob", "birth_date")
    if cur_dob and prev_dob:
        iso_cur = _normalize_date_iso(cur_dob)
        iso_prev = _normalize_date_iso(prev_dob)
        if iso_cur and iso_prev and iso_cur != iso_prev:
            mismatches.append({
                "field": "date_of_birth",
                "current_value": cur_dob,
                "historical_value": prev_dob,
                "flag": "HISTORICAL_FIELD_MISMATCH",
                "message": f"Date of Birth in this scan ({cur_dob}) differs from previous scan on {prev_date_str} ({prev_dob}) for document number {ref_doc}."
            })

    # 2. Compare Nationality / Country
    cur_nat = get_field_val(current_fields, "nationality", "country")
    prev_nat = get_field_val(prev_fields_flat, "nationality", "country")
    if cur_nat and prev_nat:
        norm_cur = _normalize_string(cur_nat)
        norm_prev = _normalize_string(prev_nat)
        if norm_cur != norm_prev and norm_cur not in norm_prev and norm_prev not in norm_cur:
            mismatches.append({
                "field": "nationality",
                "current_value": cur_nat,
                "historical_value": prev_nat,
                "flag": "HISTORICAL_FIELD_MISMATCH",
                "message": f"Nationality in this scan ({cur_nat}) differs from previous scan on {prev_date_str} ({prev_nat}) for document number {ref_doc}."
            })

    # 3. Compare Gender
    cur_gen = get_field_val(current_fields, "gender", "sex")
    prev_gen = get_field_val(prev_fields_flat, "gender", "sex")
    if cur_gen and prev_gen:
        if _normalize_gender(cur_gen) != _normalize_gender(prev_gen):
            mismatches.append({
                "field": "gender",
                "current_value": cur_gen,
                "historical_value": prev_gen,
                "flag": "HISTORICAL_FIELD_MISMATCH",
                "message": f"Gender in this scan ({cur_gen}) differs from previous scan on {prev_date_str} ({prev_gen}) for document number {ref_doc}."
            })

    return {
        "has_historical_match": True,
        "matched_scan_id": matched_record.id,
        "matched_timestamp": matched_record.timestamp.isoformat() if matched_record.timestamp else None,
        "matched_document_number": matched_record.document_number,
        "matched_holder_name": matched_record.holder_name,
        "mismatches": mismatches,
        "previous_record": {
            "id": matched_record.id,
            "timestamp": matched_record.timestamp.isoformat() if matched_record.timestamp else None,
            "document_type": matched_record.document_type,
            "holder_name": matched_record.holder_name,
            "document_number": matched_record.document_number,
            "risk_score": matched_record.risk_score,
            "risk_tier": matched_record.risk_tier,
            "status": matched_record.status,
            "fields": prev_fields_flat,
        }
    }


def re_sub_num(text: Optional[str]) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()


# ---------------------------------------------------------------------------
# Document File Retention CRUD (30-Minute Policy)
# ---------------------------------------------------------------------------

def register_document_file(
    db: Session,
    file_path: str,
    filename: str,
    scan_id: Optional[str] = None,
    session_id: Optional[str] = None,
    created_at: Optional[datetime] = None
) -> DocumentFile:
    """Registers an uploaded document image file for 30-minute retention tracking."""
    doc_file = DocumentFile(
        file_path=file_path,
        filename=filename,
        scan_id=scan_id,
        session_id=session_id,
        created_at=created_at or datetime.utcnow(),
        deleted=False
    )
    db.add(doc_file)
    db.commit()
    db.refresh(doc_file)
    return doc_file


def get_unpurged_document_files(db: Session, cutoff_time: datetime) -> List[DocumentFile]:
    """Finds all document files created on or before cutoff_time that have not yet been purged."""
    return db.query(DocumentFile).filter(
        DocumentFile.created_at <= cutoff_time,
        DocumentFile.deleted == False
    ).all()


def mark_document_file_deleted(db: Session, file_id: str) -> Optional[DocumentFile]:
    """Marks a document file record as deleted (purged from disk)."""
    doc_file = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
    if doc_file:
        doc_file.deleted = True
        doc_file.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(doc_file)
    return doc_file


# ---------------------------------------------------------------------------
# Authentication, Password Hashing & User CRUD
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hashes a plaintext password using bcrypt with random salt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username.strip().lower()).first()


def get_user_by_badge_id(db: Session, badge_id: str) -> Optional[User]:
    return db.query(User).filter(User.badge_id == badge_id.strip().upper()).first()


def create_user(
    db: Session,
    username: str,
    badge_id: str,
    officer_name: str,
    password: str,
    role: str = "officer",
    station_id: str = "hyderabad-rgia",
    must_change_password: bool = False,
    active: bool = True
) -> User:
    user = User(
        username=username.strip().lower(),
        badge_id=badge_id.strip().upper(),
        officer_name=officer_name.strip(),
        hashed_password=hash_password(password),
        role=role,
        station_id=station_id,
        must_change_password=must_change_password,
        active=active,
        created_at=datetime.utcnow()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> List[User]:
    """Lists all duty officers and administrators."""
    return db.query(User).order_by(User.id.asc()).all()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Looks up a user record by primary key ID."""
    return db.query(User).filter(User.id == user_id).first()


def update_user_password(
    db: Session,
    user_id: int,
    new_hashed_pw: str,
    must_change_password: bool = False
) -> Optional[User]:
    """Updates user password hash and updates must_change_password flag."""
    user = get_user_by_id(db, user_id)
    if user:
        user.hashed_password = new_hashed_pw
        user.must_change_password = must_change_password
        db.commit()
        db.refresh(user)
    return user


def set_user_active(db: Session, user_id: int, active: bool) -> Optional[User]:
    """Soft deactivates or reactivates a user account."""
    user = get_user_by_id(db, user_id)
    if user:
        user.active = active
        db.commit()
        db.refresh(user)
    return user


def record_user_login(db: Session, user_id: int):
    """Updates last_login timestamp upon successful authentication."""
    user = get_user_by_id(db, user_id)
    if user:
        user.last_login = datetime.utcnow()
        db.commit()



# ---------------------------------------------------------------------------
# Token Revocation & Blocklist CRUD
# ---------------------------------------------------------------------------

def revoke_token(db: Session, jti: str, token_type: str, expires_at: datetime) -> RevokedToken:
    """Adds a JWT token ID (jti) to the revocation blocklist upon logout."""
    revoked = RevokedToken(
        jti=jti,
        token_type=token_type,
        revoked_at=datetime.utcnow(),
        expires_at=expires_at
    )
    db.add(revoked)
    db.commit()
    db.refresh(revoked)
    return revoked


def is_token_revoked(db: Session, jti: str) -> bool:
    """Checks whether a token JTI has been revoked."""
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None


def cleanup_expired_revoked_tokens(db: Session):
    """Purges expired tokens from the blocklist table to keep it lean."""
    db.query(RevokedToken).filter(RevokedToken.expires_at < datetime.utcnow()).delete()
    db.commit()


