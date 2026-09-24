"""
routes_session.py - Multi-document session API endpoints.

Endpoints:
  POST /api/session                             — Create a new checkpoint session
  POST /api/session/{session_id}/document       — Upload one document into the session
  GET  /api/session/{session_id}/status         — Get session status + individual doc results
  GET  /api/session/{session_id}/report         — Generate combined cross-document report
                                                   (HTTP 400 if < 3 documents uploaded)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..db.database import SessionLocal, get_db
from ..db.session_crud import (
    add_scan_to_session,
    create_session,
    get_session,
    get_session_scans,
    save_cross_document_report,
    finalize_session,
    list_sessions,
    get_archived_session_report,
)
from ..db.crud import create_scan_record, check_scan_history
from ..modules.ocr_extraction.extractor import extract_ocr
from ..modules.document_validation.validator import validate_document
from ..modules.document_validation.cross_document_validator import cross_validate_session_documents
from ..modules.tampering_detection.detector import detect_tampering
from ..modules.face_verification.engine import get_face_engine
from ..scoring.risk_engine import calculate_risk
from ..utils.serialization import to_json_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["Multi-Document Session"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}
_MAX_FILE_SIZE = 20 * 1024 * 1024

UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads"
)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# In-memory document scan job store (mirrors routes_scan.py pattern)
_doc_jobs_lock = threading.Lock()
_DOC_JOBS: Dict[str, Dict[str, Any]] = {}


async def _read_file_safe(upload: Optional[UploadFile]) -> Optional[bytes]:
    if upload is None or not upload.filename:
        return None
    content_type = (upload.content_type or "").lower()
    if content_type and content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{content_type}'."
        )
    data = await upload.read()
    if len(data) == 0:
        return None
    if len(data) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit.")
    return data


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class SessionCreateResponse(BaseModel):
    session_id: str
    status: str = "OPEN"
    documents_required: int = 1
    documents_uploaded: int = 0
    message: str = "Session created. Multi-document protocol: each additional corroborating document increases verification coverage."


class DocumentUploadResponse(BaseModel):
    session_id: str
    scan_id: str
    document_label: str
    documents_uploaded: int
    documents_remaining: int
    documents_required: int
    status: str = "processing"
    message: str
    scan_result: Optional[Dict[str, Any]] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    documents_required: int
    documents_uploaded: int
    documents_remaining: int
    officer_id: str
    station_id: str
    created_at: str
    documents: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Background Worker: process one document in a session
# ---------------------------------------------------------------------------

def _run_session_document_worker(
    session_id: str,
    scan_id: str,
    front_bytes: bytes,
    back_bytes: Optional[bytes],
    selfie_bytes: Optional[bytes],
    document_type: str,
    document_label: str,
    officer_id: str,
    checkpoint: str,
):
    """Runs the full 4-module pipeline for one document in a session."""
    try:
        with _doc_jobs_lock:
            _DOC_JOBS[scan_id]["stage"] = "OCR Extraction"
            _DOC_JOBS[scan_id]["progress"] = 20

        ocr_result = extract_ocr(front_bytes, document_type, back_bytes)

        with _doc_jobs_lock:
            _DOC_JOBS[scan_id]["stage"] = "Document Validation"
            _DOC_JOBS[scan_id]["progress"] = 45

        validation_result = validate_document(ocr_result)

        with _doc_jobs_lock:
            _DOC_JOBS[scan_id]["stage"] = "Tampering Detection"
            _DOC_JOBS[scan_id]["progress"] = 65

        flagged_field_keys = [k for k, v in validation_result.field_cross_validation.items() if v.flag]
        tampering_result = detect_tampering(
            front_bytes,
            document_type=ocr_result.document_type.value,
            flagged_fields=flagged_field_keys
        )

        with _doc_jobs_lock:
            _DOC_JOBS[scan_id]["stage"] = "Face Verification"
            _DOC_JOBS[scan_id]["progress"] = 80

        biometrics_result = None
        if selfie_bytes:
            try:
                face_engine = get_face_engine()
                biometrics_result = face_engine.verify(front_bytes, selfie_bytes)
            except Exception as e:
                logger.warning(f"Face verify warning for {scan_id}: {e}")

        # Extract holder name and doc number
        holder_name = None
        for nk in ("name", "surname", "full_name"):
            if nk in ocr_result.extracted_fields:
                holder_name = ocr_result.extracted_fields[nk].value
                break

        doc_number = None
        for id_key in ("passport_number", "document_number", "aadhaar_number", "pan_number",
                        "dl_number", "epic_number", "visa_number"):
            if id_key in ocr_result.extracted_fields:
                doc_number = ocr_result.extracted_fields[id_key].value
                break

        # Historical check
        db_hist = SessionLocal()
        historical_check = None
        try:
            curr_fields = {k: v.value for k, v in ocr_result.extracted_fields.items()}
            historical_check = check_scan_history(
                db=db_hist,
                document_number=doc_number,
                holder_name=holder_name,
                current_fields=curr_fields,
                current_scan_id=scan_id
            )
        except Exception as e:
            logger.warning(f"History check error for {scan_id}: {e}")
        finally:
            db_hist.close()

        # Per-document risk (uses single-document context)
        risk_assessment = calculate_risk(
            ocr=ocr_result,
            validation=validation_result,
            tampering=tampering_result,
            biometrics=biometrics_result,
            historical_check=historical_check,
        )

        # Save document image
        doc_filename = f"{scan_id}_doc.jpg"
        doc_path = os.path.join(UPLOADS_DIR, doc_filename)
        try:
            with open(doc_path, "wb") as f_out:
                f_out.write(front_bytes)
            # Tag file in document_files for 30-minute automatic retention policy
            db_file = SessionLocal()
            try:
                from ..db.crud import register_document_file
                register_document_file(
                    db=db_file,
                    file_path=doc_path,
                    filename=doc_filename,
                    scan_id=scan_id,
                    session_id=session_id
                )
            finally:
                db_file.close()
        except Exception as file_err:
            logger.warning(f"Failed to write or register document file {doc_path}: {file_err}")
            doc_filename = None

        if risk_assessment.risk_tier == "CRITICAL":
            status = "REJECTED"
        elif risk_assessment.risk_tier == "HIGH":
            status = "FLAGGED"
        elif risk_assessment.risk_tier == "MEDIUM":
            status = "MANUAL_REVIEW"
        else:
            status = "PASSED"

        report_dict = {
            "scan_id": scan_id,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "officer_id": officer_id,
            "checkpoint": checkpoint,
            "document_type": ocr_result.document_type.value,
            "document_label": document_label,
            "holder_name": holder_name,
            "document_number": doc_number,
            "risk": risk_assessment.model_dump(),
            "ocr": ocr_result.model_dump(),
            "validation": validation_result.model_dump(),
            "tampering": tampering_result.model_dump(),
            "biometrics": biometrics_result.model_dump() if biometrics_result else None,
            "document_image_url": f"/api/audit/image/{doc_filename}" if doc_filename else None,
            "ela_heatmap_url": tampering_result.ela.heatmap_b64,
            "historical_check": historical_check,
        }
        report_dict = to_json_safe(report_dict)

        # Persist scan record
        db = SessionLocal()
        try:
            create_scan_record(
                db=db,
                document_type=ocr_result.document_type.value,
                holder_name=holder_name,
                document_number=doc_number,
                risk_score=risk_assessment.risk_score,
                risk_tier=risk_assessment.risk_tier,
                status=status,
                validation_passed=validation_result.is_valid,
                tampering_score=tampering_result.tampering_score,
                face_match_confidence=biometrics_result.confidence if biometrics_result else None,
                officer_id=officer_id,
                checkpoint=checkpoint,
                payload=report_dict,
                document_image_path=doc_path if doc_filename else None,
            )
        finally:
            db.close()

        # Link scan to session
        db2 = SessionLocal()
        try:
            add_scan_to_session(
                db=db2,
                session_id=session_id,
                scan_id=scan_id,
                document_type=ocr_result.document_type.value,
                document_label=document_label,
                holder_name=holder_name,
                document_number=doc_number,
                scan_payload=report_dict,
            )
        finally:
            db2.close()

        # Mark doc job complete
        with _doc_jobs_lock:
            _DOC_JOBS[scan_id].update({
                "status": "completed",
                "stage": "Completed",
                "progress": 100,
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "result": report_dict,
            })

    except Exception as e:
        logger.error(f"Session document worker error for {scan_id}: {e}", exc_info=True)
        with _doc_jobs_lock:
            _DOC_JOBS[scan_id].update({
                "status": "failed",
                "stage": "Error",
                "progress": 100,
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "error": str(e),
            })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=SessionCreateResponse,
    summary="Create New Checkpoint Session",
    description="Creates a new multi-document checkpoint session for a single traveler. Returns session_id."
)
async def create_session_endpoint(
    officer_id: str = Form("OFFICER-4819"),
    station_id: str = Form("Delhi IGI Airport (T3 Arrival)"),
    documents_required: int = Form(1),
    db: Session = Depends(get_db),
):
    if documents_required < 1:
        raise HTTPException(status_code=400, detail="documents_required must be at least 1.")
    sess = create_session(
        db=db,
        officer_id=officer_id,
        station_id=station_id,
        documents_required=documents_required,
    )
    return SessionCreateResponse(
        session_id=sess.id,
        status=sess.status,
        documents_required=sess.documents_required,
        documents_uploaded=0,
        message="Session created. Multi-document protocol: each additional corroborating document increases verification coverage.",
    )


@router.post(
    "/{session_id}/document",
    response_model=DocumentUploadResponse,
    summary="Upload Document Into Session",
    description=(
        "Uploads one document into the session, runs the full pipeline in background. "
        "Returns immediately with scan_id and current upload count."
    )
)
async def upload_session_document(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Front document image"),
    back_image: Optional[UploadFile] = File(None, description="Optional back-side image"),
    selfie_image: Optional[UploadFile] = File(None, description="Optional selfie"),
    document_type: str = Form("auto"),
    document_label: str = Form("", description="Human-readable label, e.g. 'Passport'"),
    officer_id: str = Form("OFFICER-4819"),
    sync: bool = Form(False, description="Run synchronously if True (default False)"),
    db: Session = Depends(get_db),
):
    sess = get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if sess.status != "OPEN":
        raise HTTPException(status_code=409, detail=f"Session '{session_id}' is no longer open.")

    front_bytes = await _read_file_safe(file)
    if not front_bytes:
        raise HTTPException(status_code=400, detail="Document image cannot be empty.")
    back_bytes = await _read_file_safe(back_image)
    selfie_bytes = await _read_file_safe(selfie_image)

    today_str = datetime.utcnow().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    scan_id = f"SCAN-{today_str}-{short_uuid}"

    # Auto-label if none provided
    if not document_label:
        existing_count = len(get_session_scans(db, session_id))
        document_label = f"Document {existing_count + 1}"

    now_iso = datetime.utcnow().isoformat() + "Z"
    with _doc_jobs_lock:
        _DOC_JOBS[scan_id] = {
            "scan_id": scan_id,
            "session_id": session_id,
            "document_label": document_label,
            "status": "processing",
            "stage": "Queued",
            "progress": 10,
            "error": None,
            "created_at": now_iso,
            "completed_at": None,
            "result": None,
        }

    if sync:
        await run_in_threadpool(
            _run_session_document_worker,
            session_id, scan_id, front_bytes, back_bytes, selfie_bytes,
            document_type, document_label, officer_id,
            sess.station_id,
        )
        current_count = len(get_session_scans(db, session_id))
        remaining = max(0, 1 - current_count)
        return DocumentUploadResponse(
            session_id=session_id,
            scan_id=scan_id,
            document_label=document_label,
            documents_uploaded=current_count,
            documents_remaining=remaining,
            documents_required=sess.documents_required,
            status="completed",
            message=(
                f"Document '{document_label}' processed successfully. "
                + (
                    "Report generation ready. Add more documents to increase verification coverage."
                    if current_count >= 1
                    else "Upload at least 1 document to generate report."
                )
            ),
            scan_result=_DOC_JOBS.get(scan_id, {}).get("result"),
        )

    background_tasks.add_task(
        _run_session_document_worker,
        session_id, scan_id, front_bytes, back_bytes, selfie_bytes,
        document_type, document_label, officer_id,
        sess.station_id,
    )

    # Count existing scans (excluding new one which is in-flight)
    current_count = len(get_session_scans(db, session_id))
    # +1 for the one we just dispatched
    uploaded_now = current_count + 1
    remaining = max(0, 1 - uploaded_now)

    return DocumentUploadResponse(
        session_id=session_id,
        scan_id=scan_id,
        document_label=document_label,
        documents_uploaded=uploaded_now,
        documents_remaining=remaining,
        documents_required=sess.documents_required,
        status="processing",
        message=(
            f"Document '{document_label}' is being processed. "
            + (
                "Report generation ready. Add more documents to increase verification coverage."
                if uploaded_now >= 1
                else "Upload at least 1 document to generate report."
            )
        ),
    )


@router.get(
    "/{session_id}/status",
    response_model=SessionStatusResponse,
    summary="Get Session Status",
    description="Returns current session state and individual document processing statuses.",
)
async def get_session_status(session_id: str, db: Session = Depends(get_db)):
    sess = get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    scans = get_session_scans(db, session_id)
    docs_uploaded = len(scans)
    docs_remaining = max(0, sess.documents_required - docs_uploaded)

    # Build per-document status list
    documents = []
    for link in scans:
        job = _DOC_JOBS.get(link.scan_id) or {}
        documents.append({
            "scan_id": link.scan_id,
            "document_label": link.document_label,
            "document_type": link.document_type,
            "holder_name": link.holder_name,
            "document_number": link.document_number,
            "linked_at": link.linked_at.isoformat() + "Z" if link.linked_at else None,
            "processing_status": job.get("status", "completed"),
            "processing_stage": job.get("stage", "Archived"),
            "processing_progress": job.get("progress", 100),
            "result": link.scan_payload,
        })

    # Also include in-flight jobs not yet committed to DB
    with _doc_jobs_lock:
        for scan_id, job in _DOC_JOBS.items():
            if job.get("session_id") == session_id and job.get("status") == "processing":
                if not any(d["scan_id"] == scan_id for d in documents):
                    documents.append({
                        "scan_id": scan_id,
                        "document_label": job.get("document_label", ""),
                        "document_type": None,
                        "holder_name": None,
                        "document_number": None,
                        "linked_at": None,
                        "processing_status": "processing",
                        "processing_stage": job.get("stage", "Processing"),
                        "processing_progress": job.get("progress", 10),
                        "result": None,
                    })
                    docs_uploaded = max(docs_uploaded, len(documents))

    return SessionStatusResponse(
        session_id=session_id,
        status=sess.status,
        documents_required=sess.documents_required,
        documents_uploaded=docs_uploaded,
        documents_remaining=max(0, sess.documents_required - docs_uploaded),
        officer_id=sess.officer_id,
        station_id=sess.station_id,
        created_at=sess.created_at.isoformat() + "Z" if sess.created_at else "",
        documents=documents,
    )


@router.get(
    "/{session_id}/report",
    summary="Generate Combined Cross-Document Session Report",
    description=(
        "Generates the combined session report with cross-document identity validation. "
        "Returns HTTP 400 with INSUFFICIENT_DOCUMENTS error if no documents have been uploaded."
    ),
)
async def get_session_report(session_id: str, db: Session = Depends(get_db)):
    try:
        sess = get_session(db, session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        scans = get_session_scans(db, session_id)
        docs_uploaded = len(scans)
        docs_required = sess.documents_required

        # Guard — at least 1 document required to generate report
        if docs_uploaded < 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INSUFFICIENT_DOCUMENTS",
                    "message": "Cannot generate report: No documents uploaded. Please upload at least 1 document.",
                    "documents_uploaded": 0,
                    "documents_required": 1,
                    "documents_remaining": 1,
                    "session_id": session_id,
                }
            )

        # Check for any still-processing documents
        in_progress = []
        with _doc_jobs_lock:
            for scan_id, job in _DOC_JOBS.items():
                if job.get("session_id") == session_id and job.get("status") == "processing":
                    in_progress.append(scan_id)

        if in_progress:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "DOCUMENTS_STILL_PROCESSING",
                    "message": f"{len(in_progress)} document(s) are still being processed. Please retry in a moment.",
                    "processing_scans": in_progress,
                }
            )

        # Strict session boundary verification: explicitly ensure every scan belongs exclusively to session_id
        for link in scans:
            if str(link.session_id) != str(session_id):
                raise HTTPException(
                    status_code=400,
                    detail=f"Security violation: scan '{link.scan_id}' does not belong to session '{session_id}'."
                )

        # Gather all scan payloads for cross-document comparison
        session_scan_dicts = [
            {
                "scan_id": link.scan_id,
                "document_type": link.document_type,
                "document_label": link.document_label or link.document_type or "Document",
                "holder_name": link.holder_name,
                "document_number": link.document_number,
                "scan_payload": link.scan_payload or {},
            }
            for link in scans
        ]

        # Run cross-document validation
        cross_doc_result = await run_in_threadpool(
            cross_validate_session_documents, session_scan_dicts
        )

        # Aggregate risk: use worst individual-document risk + cross-doc penalty
        individual_risks = []
        for link in scans:
            payload = link.scan_payload or {}
            risk = payload.get("risk") or {}
            individual_risks.append({
                "scan_id": link.scan_id,
                "document_label": link.document_label,
                "risk_score": risk.get("risk_score", 0.0),
                "risk_tier": risk.get("risk_tier", "LOW"),
                "factors": risk.get("factors", []),
                "clear_factors": risk.get("clear_factors", []),
            })

        # Compute combined session score
        max_individual_score = max((r["risk_score"] for r in individual_risks), default=0.0)

        # Apply cross-doc mismatch penalty on top of worst individual score
        cross_doc_penalty = 0.0
        if cross_doc_result.get("has_cross_document_mismatch"):
            n_mismatched = len(cross_doc_result.get("mismatched_fields", []))
            cross_doc_penalty = min(50.0, n_mismatched * 50.0)
            # Non-dilution: cross-doc mismatch floor is 75.0
            session_risk_score = max(75.0, min(100.0, max_individual_score + cross_doc_penalty))
        else:
            # Corroboration bonus: consistent docs lower risk slightly
            corr = cross_doc_result.get("corroboration_factor", 0.0)
            session_risk_score = max(0.0, max_individual_score * (1.0 - corr * 0.05))

        session_risk_score = round(min(100.0, session_risk_score), 1)

        if session_risk_score <= 25.0:
            session_tier = "LOW"
            session_action = "CLEAR"
        elif session_risk_score <= 55.0:
            session_tier = "MEDIUM"
            session_action = "SECONDARY_INSPECTION"
        elif session_risk_score <= 80.0:
            session_tier = "HIGH"
            session_action = "SUPERVISOR_REVIEW"
        else:
            session_tier = "CRITICAL"
            session_action = "INTERDICT_IMMEDIATE"

        coverage_tier = "none" if docs_uploaded == 0 else ("partial" if docs_uploaded == 1 else "strong")
        if docs_uploaded == 1:
            summary_text = (
                "Single document verified with partial coverage. "
                "No cross-document discrepancies detected. "
                "Additional corroborating documents activate cross-document checks."
            )
        else:
            summary_text = cross_doc_result.get("summary", "")

        # Build combined report
        combined_report = {
            "session_id": session_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "officer_id": sess.officer_id,
            "station_id": sess.station_id,
            "documents_submitted": docs_uploaded,
            "documents_required": 1,
            "coverage": coverage_tier,
            "session_risk_score": session_risk_score,
            "session_risk_tier": session_tier,
            "session_action": session_action,
            "cross_document_validation": cross_doc_result,
            "individual_documents": individual_risks,
            "document_details": session_scan_dicts,
            "summary": summary_text,
        }
        combined_report = to_json_safe(combined_report)

        # Persist cross-doc report
        try:
            db2 = SessionLocal()
            save_cross_document_report(db2, session_id, combined_report)
            db2.close()
        except Exception as e:
            logger.warning(f"Could not persist cross-doc report for {session_id}: {e}")

        return combined_report

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"Failed to generate cross-document report for session {session_id}: {exc}",
            exc_info=True,
        )
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to generate cross-document report",
                "detail": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
        )


# ---------------------------------------------------------------------------
# Session Lifecycle & Audit Endpoints
# ---------------------------------------------------------------------------

class SessionCompleteRequest(BaseModel):
    decision: Optional[str] = "CLEARED"  # APPROVED, FLAGGED, REJECTED, DETAINED, CLEARED, DISCARDED
    officer_id: Optional[str] = "OFFICER-4819"
    checkpoint: Optional[str] = "Delhi IGI Airport (T3 Arrival)"
    status: Optional[str] = "COMPLETE"  # COMPLETE, DISCARDED
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    findings: Optional[str] = None


@router.post(
    "/{session_id}/complete",
    summary="Finalize and Archive Checkpoint Session",
    description="Writes the completed session to the permanent audit log and finalizes its lifecycle state."
)
async def complete_session_endpoint(
    session_id: str,
    body: Optional[SessionCompleteRequest] = None,
    db: Session = Depends(get_db),
):
    sess = get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    decision = body.decision if body and body.decision else "CLEARED"
    officer_id = body.officer_id if body and body.officer_id else sess.officer_id
    checkpoint = body.checkpoint if body and body.checkpoint else sess.station_id
    status = body.status if body and body.status else "COMPLETE"
    risk_score = body.risk_score if body else None
    risk_tier = body.risk_tier if body else None
    findings = body.findings if body else None

    finalized = finalize_session(
        db=db,
        session_id=session_id,
        decision=decision,
        officer_id=officer_id,
        checkpoint=checkpoint,
        status=status,
        risk_score=risk_score,
        risk_tier=risk_tier,
        findings_summary=findings,
    )

    return {
        "status": "ok",
        "message": f"Session '{session_id}' finalized with decision '{decision}' and archived to audit log.",
        "session_id": session_id,
        "session_status": finalized.status,
        "completed_at": finalized.completed_at.isoformat() + "Z" if finalized.completed_at else None,
        "decision": finalized.decision,
    }


@router.get(
    "",
    summary="List Checkpoint Sessions for Audit Trail",
    description="Retrieves a list of completed and archived traveler sessions with risk scores, decisions, and metadata.",
)
async def list_sessions_endpoint(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    items, total = list_sessions(db=db, status=status, skip=skip, limit=limit)
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": items,
    }


@router.get(
    "/{session_id}/archived-report",
    summary="Get Archived Cross-Document Session Report",
    description="Retrieves the read-only archived cross-document report for a completed session."
)
async def get_archived_report_endpoint(session_id: str, db: Session = Depends(get_db)):
    sess = get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    report = get_archived_session_report(db, session_id)
    if not report:
        # Fallback to generating report if not yet saved
        return await get_session_report(session_id, db)

    # Assert report session scoping
    if report.get("session_id") != session_id:
        raise HTTPException(status_code=500, detail="Data integrity error: Archived report session ID mismatch.")

    return report


