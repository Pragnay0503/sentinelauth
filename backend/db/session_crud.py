"""
session_crud.py - CRUD operations for ScanSession (multi-document checkpoint sessions).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .session_models import ScanSession, SessionScanLink
from ..utils.serialization import to_json_safe


def create_session(
    db: Session,
    session_id: Optional[str] = None,
    required_docs: Optional[int] = None,
    checkpoint: Optional[str] = None,
    officer_id: str = "OFFICER-4819",
    documents_required: int = 3,
    station_id: str = "Delhi IGI Airport (T3 Arrival)",
) -> ScanSession:
    if session_id is None:
        from .session_models import generate_session_id
        session_id = generate_session_id()
    docs_req = required_docs if required_docs is not None else documents_required
    st_id = checkpoint if checkpoint is not None else station_id
    sess = ScanSession(
        id=session_id,
        documents_required=docs_req,
        station_id=st_id,
        officer_id=officer_id,
        status="OPEN",
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def get_session(db: Session, session_id: str) -> Optional[ScanSession]:
    return db.query(ScanSession).filter(ScanSession.id == session_id).first()


def add_scan_to_session(
    db: Session,
    session_id: str,
    scan_id: str,
    document_type: str,
    document_label: str,
    holder_name: Optional[str],
    document_number: Optional[str],
    scan_payload: Dict[str, Any],
) -> SessionScanLink:
    safe_payload = to_json_safe(scan_payload)
    link = SessionScanLink(
        session_id=session_id,
        scan_id=scan_id,
        document_type=str(document_type),
        document_label=str(document_label),
        holder_name=str(holder_name) if holder_name is not None else None,
        document_number=str(document_number) if document_number is not None else None,
        scan_payload=safe_payload,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_session_scans(db: Session, session_id: str) -> List[SessionScanLink]:
    return (
        db.query(SessionScanLink)
        .filter(SessionScanLink.session_id == session_id)
        .order_by(SessionScanLink.linked_at)
        .all()
    )


def save_cross_document_report(
    db: Session, session_id: str, report: Dict[str, Any]
) -> Optional[ScanSession]:
    sess = get_session(db, session_id)
    if sess is None:
        return None
    sess.cross_document_report = to_json_safe(report)
    sess.status = "COMPLETE"
    sess.completed_at = datetime.utcnow()
    sess.risk_score = str(report.get("session_risk_score", 0.0))
    sess.risk_tier = report.get("session_risk_tier", "LOW")
    sess.findings_summary = report.get("summary", "")
    if not sess.decision:
        sess.decision = report.get("session_action", "CLEARED")
    db.commit()
    db.refresh(sess)
    return sess


def finalize_session(
    db: Session,
    session_id: str,
    decision: Optional[str] = None,
    officer_id: Optional[str] = None,
    checkpoint: Optional[str] = None,
    status: str = "COMPLETE",
    risk_score: Optional[float] = None,
    risk_tier: Optional[str] = None,
    document_types: Optional[str] = None,
    findings_summary: Optional[str] = None,
) -> Optional[ScanSession]:
    sess = get_session(db, session_id)
    if sess is None:
        return None
    sess.status = status
    sess.completed_at = datetime.utcnow()
    if decision:
        sess.decision = decision
    if officer_id:
        sess.officer_id = officer_id
    if checkpoint:
        sess.station_id = checkpoint

    if risk_score is not None:
        sess.risk_score = str(risk_score)
    elif sess.cross_document_report:
        sess.risk_score = str(sess.cross_document_report.get("session_risk_score", "0.0"))
        if not risk_tier:
            risk_tier = sess.cross_document_report.get("session_risk_tier", "LOW")

    if risk_tier:
        sess.risk_tier = risk_tier

    if document_types:
        sess.document_types = document_types
    else:
        scans = get_session_scans(db, session_id)
        types = [s.document_type for s in scans if s.document_type]
        if types:
            sess.document_types = ", ".join(types)

    if findings_summary:
        sess.findings_summary = findings_summary
    elif sess.cross_document_report:
        sess.findings_summary = sess.cross_document_report.get("summary", "")

    db.commit()
    db.refresh(sess)
    return sess


from .screening_history import ScreeningHistoryRecord, mask_document_number


def list_sessions(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[List[Dict[str, Any]], int]:
    q = db.query(ScanSession)
    if status and status.upper() != "ALL":
        q = q.filter(ScanSession.status == status.upper())

    total = q.count()
    sessions = q.order_by(ScanSession.created_at.desc()).offset(skip).limit(limit).all()

    items = []
    for s in sessions:
        scans = get_session_scans(db, s.id)
        screening_records = (
            db.query(ScreeningHistoryRecord)
            .filter(ScreeningHistoryRecord.session_id == s.id)
            .order_by(ScreeningHistoryRecord.timestamp.asc())
            .all()
        )

        # 1. Document count
        doc_count = max(len(scans), len(screening_records))
        if doc_count == 0:
            doc_count = 1

        # 2. Document types (never fallback to "N/A")
        doc_types_list = []
        if s.document_types and s.document_types != "N/A":
            doc_types_list = [dt.strip() for dt in s.document_types.split(",") if dt.strip()]

        if not doc_types_list and screening_records:
            doc_types_list = [r.document_type for r in screening_records if r.document_type]

        if not doc_types_list and scans:
            doc_types_list = [sc.document_type for sc in scans if sc.document_type]

        if doc_types_list:
            seen = set()
            unique_types = [x for x in doc_types_list if not (x in seen or seen.add(x))]
            doc_types = ", ".join(unique_types)
            primary_doc_type = unique_types[0]
        else:
            doc_types = "passport"
            primary_doc_type = "passport"

        # 3. Masked Document Number (e.g. XXXX XXXX 1107, AD****43)
        masked_doc_num = None
        if screening_records:
            for r in screening_records:
                if r.document_number and r.document_number != "N/A":
                    masked_doc_num = r.document_number
                    break
        if not masked_doc_num and scans:
            for sc in scans:
                if sc.document_number and sc.document_number != "N/A":
                    masked_doc_num = mask_document_number(sc.document_number, sc.document_type or "")
                    break
        if not masked_doc_num:
            masked_doc_num = "N/A"

        # 4. Traveller Name
        traveller_name = None
        if screening_records:
            for r in screening_records:
                if r.name and r.name != "N/A":
                    traveller_name = r.name
                    break
        if not traveller_name and scans:
            for sc in scans:
                if sc.holder_name and sc.holder_name != "N/A":
                    traveller_name = sc.holder_name
                    break
        if not traveller_name:
            traveller_name = "N/A"

        # 5. Screening Decision / Outcome
        score = s.risk_score
        tier = s.risk_tier
        findings = s.findings_summary

        decision = None
        if screening_records:
            outcomes = [r.outcome.upper() for r in screening_records if r.outcome]
            if "TAMPERED" in outcomes:
                decision = "TAMPERED"
            elif "EXPIRED" in outcomes:
                decision = "EXPIRED"
            elif "SKIPPED" in outcomes and len(outcomes) == 1:
                decision = "SKIPPED"
            elif any(o == "VERIFIED" for o in outcomes):
                decision = "VERIFIED"
            else:
                decision = outcomes[-1] if outcomes else "VERIFIED"
        elif scans:
            has_tamper = any(
                sc.scan_payload and (
                    sc.scan_payload.get("status") in ("REJECTED", "FAILED") or
                    sc.scan_payload.get("risk", {}).get("risk_tier") in ("HIGH", "CRITICAL")
                )
                for sc in scans
            )
            decision = "TAMPERED" if has_tamper else "VERIFIED"
        elif s.cross_document_report and s.cross_document_report.get("session_action"):
            act = s.cross_document_report.get("session_action", "").upper()
            if act in ("REJECTED", "DETAINED"):
                decision = "TAMPERED"
            elif act in ("APPROVED", "CLEARED"):
                decision = "VERIFIED"
            else:
                decision = act
        elif s.decision:
            d_upper = s.decision.upper()
            if d_upper in ("APPROVED", "CLEARED"):
                decision = "VERIFIED"
            elif d_upper in ("REJECTED", "DETAINED"):
                decision = "TAMPERED"
            else:
                decision = d_upper
        else:
            decision = "VERIFIED" if s.status == "COMPLETE" else "OPEN"

        if s.cross_document_report:
            if not score:
                score = str(s.cross_document_report.get("session_risk_score", 0.0))
            if not tier:
                tier = s.cross_document_report.get("session_risk_tier", "LOW")
            if not findings:
                findings = s.cross_document_report.get("summary", "")
        elif screening_records and not score:
            score = str(max((r.risk_score for r in screening_records), default=0.0))

        items.append({
            "session_id": s.id,
            "created_at": s.created_at.isoformat() + "Z" if s.created_at else None,
            "completed_at": s.completed_at.isoformat() + "Z" if s.completed_at else (s.created_at.isoformat() + "Z" if s.created_at else None),
            "officer_id": s.officer_id,
            "checkpoint": s.station_id,
            "status": s.status,
            "decision": decision,
            "outcome": decision,
            "risk_score": float(score) if score is not None else 0.0,
            "risk_tier": tier or "LOW",
            "document_type": primary_doc_type,
            "document_types": doc_types,
            "documents_count": doc_count,
            "document_number": masked_doc_num,
            "masked_document_number": masked_doc_num,
            "name": traveller_name,
            "traveller_name": traveller_name,
            "findings": findings or "No discrepancies flagged.",
            "has_report": bool(s.cross_document_report),
        })

    return items, total


def get_archived_session_report(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    sess = get_session(db, session_id)
    if sess is None:
        return None
    if sess.cross_document_report:
        return sess.cross_document_report
    return None


def close_session(db: Session, session_id: str) -> Optional[ScanSession]:
    sess = get_session(db, session_id)
    if sess:
        sess.status = "COMPLETE"
        sess.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(sess)
    return sess

