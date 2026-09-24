"""
routes_scan.py - Complete suite of document screening endpoints.
Exposes:
  - POST /api/scan/full         (Background Task Orchestration: OCR, Validation, Tampering, Biometrics, Risk)
  - GET  /api/scan/{scan_id}/status (Polling Endpoint for Async Status & Result)
  - POST /api/scan/ocr          (Module 1 — Fast Background/Sync OCR)
  - POST /api/scan/validate     (Module 2 — Validation)
  - POST /api/scan/tampering    (Module 3 — Forensics)
  - POST /api/scan/face-verify  (Module 4 — Biometrics)
"""
from __future__ import annotations

import io
import logging
import os
import threading
import uuid
import hashlib
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

import cv2
import numpy as np

from ..db.database import SessionLocal, get_db
from ..db.crud import check_scan_history, create_scan_record, get_scan_by_id
from ..db.screening_history import create_screening_record
from ..modules.ocr_extraction.extractor import extract_ocr
from ..modules.ocr_extraction.schemas import OCRResult
from ..modules.document_validation.validator import validate_document
from ..modules.document_validation.schemas import ValidationResult
from ..modules.tampering_detection.detector import detect_tampering
from ..modules.tampering_detection.schemas import TamperingResult
from ..modules.face_verification.engine import get_face_engine
from ..modules.face_verification.schemas import FaceVerifyResult, MorphDetectionResult
from ..modules.face_verification.morph_detection import detect_morphing
from ..modules.validation.qr_check import verify_document_qr
from ..scoring.risk_engine import calculate_risk
from ..scoring.schemas import FullScanReport, RiskAssessment
from ..utils.serialization import to_json_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scan", tags=["Document Screening"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# In-Memory Background Job Store
# ---------------------------------------------------------------------------

_scan_jobs_lock = threading.Lock()
_SCAN_JOBS: Dict[str, Dict[str, Any]] = {}


def _update_job(scan_id: str, **kwargs):
    with _scan_jobs_lock:
        if scan_id in _SCAN_JOBS:
            _SCAN_JOBS[scan_id].update(kwargs)


def _get_job(scan_id: str) -> Optional[Dict[str, Any]]:
    with _scan_jobs_lock:
        job = _SCAN_JOBS.get(scan_id)
        return dict(job) if job else None


class ScanJobStatusResponse(BaseModel):
    scan_id: str
    status: str = Field(..., description="processing, completed, failed")
    stage: str = Field("queued", description="Current execution stage")
    progress: int = Field(0, ge=0, le=100, description="Estimated progress 0-100%")
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Any] = None


class AsyncScanResponse(BaseModel):
    scan_id: str
    status: str = "processing"
    stage: str = "queued"
    progress: int = 10
    message: str = "Screening job accepted and running in background"


async def _read_file_safe(upload: Optional[UploadFile]) -> Optional[bytes]:
    if upload is None or not upload.filename:
        return None
    content_type = (upload.content_type or "").lower()
    if content_type and content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{content_type}'. Supported formats: {sorted(_ALLOWED_TYPES)}"
        )
    data = await upload.read()
    if len(data) == 0:
        return None
    if len(data) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Uploaded file exceeds limit of 20 MB."
        )
    return data


# ---------------------------------------------------------------------------
# Background Task Workers
# ---------------------------------------------------------------------------

def _run_ocr_background_worker(
    scan_id: str,
    front_bytes: bytes,
    document_type: str,
    back_bytes: Optional[bytes]
):
    """Background worker for /api/scan/ocr."""
    try:
        _update_job(scan_id, stage="Running Region OCR Pipeline...", progress=40)
        res = extract_ocr(front_bytes, document_type, back_bytes)
        _update_job(
            scan_id,
            status="completed",
            stage="Completed",
            progress=100,
            completed_at=datetime.utcnow().isoformat() + "Z",
            result=res.model_dump()
        )
    except Exception as e:
        logger.error(f"Background OCR error for {scan_id}: {e}", exc_info=True)
        _update_job(
            scan_id,
            status="failed",
            stage="Error",
            progress=100,
            completed_at=datetime.utcnow().isoformat() + "Z",
            error=str(e)
        )


def _get_field_value(field_obj: Any) -> Optional[str]:
    """
    Safely extract string value from any field representation:
    1. Plain string (e.g. "AD735443")
    2. Dict with a "value" key (e.g. {"value": "AD735443", "confidence": 0.98})
    3. Object with a .value attribute (e.g. FieldResult(value="AD735443"))
    """
    if field_obj is None:
        return None
    if isinstance(field_obj, str):
        return field_obj
    if isinstance(field_obj, dict):
        val = field_obj.get("value")
        return str(val) if val is not None else None
    if hasattr(field_obj, "value"):
        val = getattr(field_obj, "value")
        return str(val) if val is not None else None
    return str(field_obj)


def _persist_to_screening_history(
    *,
    scan_id: str,
    officer_id: str,
    ocr_result: OCRResult,
    validation_result: ValidationResult,
    tampering_result: TamperingResult,
    biometrics_result: Optional[FaceVerifyResult],
    risk_assessment: RiskAssessment,
    historical_check: Optional[Dict[str, Any]],
    qr_verification: Optional[Dict[str, Any]],
    front_bytes: bytes,
    processing_time_ms: float,
    session_id: Optional[str] = None,
    status: str = "PASSED",
) -> Optional[Any]:
    """
    Appends an immutable record to the screening_history table after each completed screening.
    Never updates or deletes; strictly append-only.
    """
    try:
        from ..modules.validation.mrz_cross_check import normalize_nationality_to_code

        fields_dict = getattr(ocr_result, "extracted_fields", {}) or {}

        # 1. Document Number
        doc_number = ""
        for id_key in ("passport_number", "document_number", "aadhaar_number", "pan_number", "dl_number", "epic_number", "visa_number"):
            if id_key in fields_dict:
                val = _get_field_value(fields_dict[id_key])
                if val:
                    doc_number = val
                    break

        # 2. Holder Name
        holder_name = None
        if "name" in fields_dict:
            holder_name = _get_field_value(fields_dict["name"])
        elif "surname" in fields_dict:
            holder_name = _get_field_value(fields_dict["surname"])

        # 3. Date of Birth
        dob = None
        for k in ("dob", "date_of_birth", "birth_date"):
            if k in fields_dict:
                val = _get_field_value(fields_dict[k])
                if val:
                    dob = val
                    break

        # 4. Nationality (normalized to ISO 3166-1 alpha-3 code)
        nationality = None
        for k in ("nationality", "country", "issuing_country", "nationality_code"):
            if k in fields_dict:
                raw_nat = _get_field_value(fields_dict[k])
                if raw_nat:
                    nationality = normalize_nationality_to_code(raw_nat)
                break

        # 5. Outcome determination: VERIFIED / TAMPERED / EXPIRED / SKIPPED / UNKNOWN
        is_expired = getattr(validation_result, "is_expired", False)
        for v in getattr(validation_result, "violations", []):
            msg = getattr(v, "rule_violated", str(v))
            if "expire" in msg.lower():
                is_expired = True
                break
        if hasattr(validation_result, "errors") and validation_result.errors:
            for err in validation_result.errors:
                if "expire" in str(err).lower():
                    is_expired = True
                    break
        for factor in (risk_assessment.factors or []):
            if "expire" in factor.title.lower() or "expire" in factor.description.lower():
                is_expired = True
                break

        if is_expired:
            outcome = "EXPIRED"
        elif tampering_result.is_tampered or risk_assessment.risk_tier in ("CRITICAL", "HIGH") or status in ("REJECTED", "FLAGGED"):
            outcome = "TAMPERED"
        elif status == "PASSED" or risk_assessment.risk_tier == "LOW":
            outcome = "VERIFIED"
        elif status == "MANUAL_REVIEW" or risk_assessment.risk_tier == "MEDIUM":
            has_tamper = any(f.category == "TAMPERING" for f in (risk_assessment.factors or []))
            outcome = "TAMPERED" if has_tamper else "UNKNOWN"
        else:
            outcome = "UNKNOWN"

        # 6. Granular Checks Dictionary
        checks: Dict[str, Dict[str, str]] = {}

        # MRZ Checksum
        if getattr(ocr_result, "mrz_applicable", False):
            if ocr_result.mrz_validation_passed is True:
                checks["mrz_checksum"] = {"status": "PASSED", "reason": "All MRZ check digits and format valid"}
            elif ocr_result.mrz_validation_passed is False:
                checks["mrz_checksum"] = {"status": "FAILED", "reason": "MRZ checksum or format verification failed"}
            else:
                checks["mrz_checksum"] = {"status": "NOT_EVALUATED", "reason": "MRZ detected but checksums could not be evaluated"}
        else:
            checks["mrz_checksum"] = {"status": "NOT_EVALUATED", "reason": "MRZ zone not applicable for this document type"}

        # Visual Format
        if validation_result.is_valid:
            checks["visual_format"] = {"status": "PASSED", "reason": "Document structure, mandatory fields, and format rules valid"}
        else:
            err_msgs = [getattr(v, "rule_violated", str(v)) for v in getattr(validation_result, "violations", [])]
            if hasattr(validation_result, "errors") and validation_result.errors:
                err_msgs.extend(str(e) for e in validation_result.errors)
            err_reason = "; ".join(err_msgs[:2]) if err_msgs else "Document format or mandatory field rules violated"
            checks["visual_format"] = {"status": "FAILED", "reason": err_reason}

        # Tampering Forensics
        if tampering_result.is_tampered or tampering_result.tampering_score >= 40.0:
            tamper_reasons = tampering_result.details.get("reasons", []) if tampering_result.details else []
            t_rsn = "; ".join(tamper_reasons) if tamper_reasons else f"Tampering score {tampering_result.tampering_score:.1f}/100 exceeds safe threshold"
            checks["tampering_forensics"] = {"status": "FAILED", "reason": t_rsn}
        else:
            checks["tampering_forensics"] = {"status": "PASSED", "reason": f"No localized tampering detected (score: {tampering_result.tampering_score:.1f}/100)"}

        # Face Match
        if biometrics_result is None or biometrics_result.status == "NO_SELFIE_PROVIDED":
            checks["face_match"] = {"status": "NOT_EVALUATED", "reason": "Live presentation portrait not submitted"}
        elif biometrics_result.match:
            checks["face_match"] = {"status": "PASSED", "reason": f"Face match confidence {biometrics_result.confidence * 100:.1f}% (similarity {biometrics_result.cosine_similarity:.3f})"}
        else:
            checks["face_match"] = {"status": "FAILED", "reason": f"Face mismatch: similarity {biometrics_result.cosine_similarity:.3f} below threshold {biometrics_result.threshold_applied}"}

        # Face Morph S-MAD
        if biometrics_result and biometrics_result.morph_analysis:
            ma = biometrics_result.morph_analysis
            if getattr(ma, "is_morphed", False):
                checks["face_morph_smad"] = {"status": "FAILED", "reason": f"S-MAD detected suspicious morph signature (score {getattr(ma, 'morph_score', 0.0):.2f})"}
            else:
                checks["face_morph_smad"] = {"status": "PASSED", "reason": f"Document portrait verified natural (morph score {getattr(ma, 'morph_score', 0.0):.2f})"}
        else:
            checks["face_morph_smad"] = {"status": "NOT_EVALUATED", "reason": "Face morph analysis not evaluated"}

        # QR Verification
        if qr_verification and qr_verification.get("outcome") == "VERIFIED":
            checks["qr_verification"] = {"status": "PASSED", "reason": qr_verification.get("reason", "Cryptographic QR verified")}
        elif qr_verification and qr_verification.get("outcome") == "TAMPERED":
            checks["qr_verification"] = {"status": "FAILED", "reason": qr_verification.get("reason", "Cryptographic QR signature mismatch or tampered data")}
        else:
            qr_rsn = qr_verification.get("reason", "No scannable cryptographic QR code detected") if qr_verification else "No scannable cryptographic QR code detected"
            checks["qr_verification"] = {"status": "NOT_EVALUATED", "reason": qr_rsn}

        # Watchlist Screening
        watchlist_matched = getattr(validation_result, "watchlist_match", False) or (validation_result.details and validation_result.details.get("watchlist_screening", {}).get("matched"))
        if watchlist_matched:
            checks["watchlist_screening"] = {"status": "FAILED", "reason": "Holder matched against security/law-enforcement watchlist"}
        else:
            checks["watchlist_screening"] = {"status": "PASSED", "reason": "Zero matches against international or national watchlists"}

        # Identity Continuity
        if historical_check and historical_check.get("anomaly_detected"):
            checks["identity_continuity"] = {"status": "FAILED", "reason": historical_check.get("anomaly_reason", "Inconsistent identity records detected in history")}
        elif historical_check and historical_check.get("repeat_visitor"):
            checks["identity_continuity"] = {"status": "PASSED", "reason": f"Verified repeat traveler across {historical_check.get('total_scans', 1)} prior screenings"}
        else:
            checks["identity_continuity"] = {"status": "PASSED", "reason": "First-time screening; no conflicting historical identity recorded"}

        # 7. Producing Check and Field
        flagged_field_keys = [k for k, v in validation_result.field_cross_validation.items() if getattr(v, "flag", False)]
        producing_check = None
        producing_field = None
        if outcome == "VERIFIED":
            producing_check = "ALL_CHECKS_PASSED"
            producing_field = None
        else:
            if risk_assessment.factors:
                top_factor = max(risk_assessment.factors, key=lambda f: f.points_added)
                producing_check = top_factor.title
                if tampering_result.details and tampering_result.details.get("tampered_fields"):
                    producing_field = tampering_result.details["tampered_fields"][0]
                elif flagged_field_keys:
                    producing_field = flagged_field_keys[0]
                else:
                    desc_lower = (top_factor.description + " " + top_factor.title).lower()
                    for cand in ("passport_number", "document_number", "aadhaar_number", "pan_number", "dl_number", "name", "date_of_birth", "dob", "date_of_expiry", "expiry_date", "nationality", "mrz", "photo", "face", "qr", "watchlist"):
                        if cand in desc_lower:
                            producing_field = cand
                            break
            if not producing_check:
                if outcome == "EXPIRED":
                    producing_check = "DOCUMENT_EXPIRATION"
                    producing_field = "date_of_expiry"
                elif outcome == "TAMPERED":
                    producing_check = "FORENSIC_TAMPERING_CHECK"
                    producing_field = flagged_field_keys[0] if flagged_field_keys else None
                else:
                    producing_check = "RISK_EVALUATION"
                    producing_field = None

        # 8. Document Image SHA-256 Hash
        image_hash = hashlib.sha256(front_bytes).hexdigest() if front_bytes else None

        # 9. Write to screening_history via create_screening_record
        db = SessionLocal()
        try:
            record = create_screening_record(
                db=db,
                screening_id=scan_id,
                officer_id=officer_id,
                document_type=ocr_result.document_type.value,
                document_number=doc_number,
                name=holder_name,
                dob=dob,
                nationality=nationality,
                outcome=outcome,
                risk_score=risk_assessment.risk_score,
                checks=checks,
                producing_check=producing_check,
                producing_field=producing_field,
                session_id=session_id,
                image_hash=image_hash,
                processing_time_ms=processing_time_ms,
            )
            return record
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to persist screening history for {scan_id}: {e}", exc_info=True)
        return None


def _run_full_scan_background_worker(
    scan_id: str,
    front_bytes: bytes,
    back_bytes: Optional[bytes],
    selfie_bytes: Optional[bytes],
    document_type: str,
    officer_id: str,
    checkpoint: str,
    session_id: Optional[str] = None
):
    """Background worker executing the complete 4-module pipeline and persistence."""
    start_time = time.perf_counter()
    try:
        # 1. Module 1: OCR Extraction
        _update_job(scan_id, stage="Downscaling & Extracting Document Fields...", progress=20)
        ocr_result: OCRResult = extract_ocr(front_bytes, document_type, back_bytes)

        # 1b. Module 1b: QR Code Verification & Evidence Extraction (Under 200ms)
        qr_verification: Optional[Dict[str, Any]] = None
        try:
            front_arr = cv2.imdecode(np.frombuffer(front_bytes, np.uint8), cv2.IMREAD_COLOR)
            if front_arr is not None:
                p_fields = {k: (v.value, v.confidence) for k, v in ocr_result.extracted_fields.items()}
                qr_verification = verify_document_qr(
                    image=front_arr,
                    document_type=ocr_result.document_type.value,
                    doc_id=scan_id,
                    printed_fields=p_fields
                )
                if qr_verification.get("outcome") == "NOT_EVALUATED" and back_bytes:
                    back_arr = cv2.imdecode(np.frombuffer(back_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if back_arr is not None:
                        qr_back = verify_document_qr(
                            image=back_arr,
                            document_type=ocr_result.document_type.value,
                            doc_id=scan_id + "_back",
                            printed_fields=p_fields
                        )
                        if qr_back.get("outcome") in ("VERIFIED", "TAMPERED"):
                            qr_verification = qr_back
        except Exception as qr_err:
            logger.warning(f"QR verification error for {scan_id}: {qr_err}")

        if qr_verification:
            ocr_result.checksum_validation["qr_verification"] = (
                True if qr_verification.get("outcome") == "VERIFIED"
                else (False if qr_verification.get("outcome") == "TAMPERED" else None)
            )
            ocr_result.checksum_validation["uidai_qr_verified"] = (
                True if qr_verification.get("outcome") == "VERIFIED"
                else (False if qr_verification.get("outcome") == "TAMPERED" else None)
            )
            ocr_result.checksum_validation["qr_outcome"] = qr_verification.get("outcome")
            ocr_result.checksum_validation["qr_signature_status"] = qr_verification.get("signature_status")
            ocr_result.checksum_validation["qr_signature_note"] = qr_verification.get("signature_note")
            ocr_result.checksum_validation["qr_reason"] = qr_verification.get("reason")

        # 2. Module 2: Document Validation & Watchlists
        _update_job(scan_id, stage="Validating Document Format, Checksums & Watchlists...", progress=45)
        validation_result: ValidationResult = validate_document(ocr_result)
        if qr_verification:
            validation_result.details["qr_verification"] = qr_verification

        # 3. Module 3: Image Forensics & Localized Field Tampering Detection
        _update_job(scan_id, stage="Generating ELA Heatmap & Localized Field Forensics...", progress=70)
        flagged_field_keys = [k for k, v in validation_result.field_cross_validation.items() if v.flag]
        tampering_result: TamperingResult = detect_tampering(
            front_bytes,
            document_type=ocr_result.document_type.value,
            flagged_fields=flagged_field_keys
        )

        # 4. Module 4: Biometric Face Verification & S-MAD Face Morphing Attack Detection
        biometrics_result: Optional[FaceVerifyResult] = None
        _update_job(scan_id, stage="Analyzing Biometric Face Embedding & S-MAD Morph Signatures...", progress=85)
        try:
            morph_res = detect_morphing(front_bytes)
            if selfie_bytes is not None:
                face_engine = get_face_engine()
                biometrics_result = face_engine.verify(front_bytes, selfie_bytes)
                biometrics_result.morph_analysis = morph_res
            else:
                biometrics_result = FaceVerifyResult(
                    match=False,
                    confidence=0.0,
                    cosine_similarity=0.0,
                    l2_distance=999.0,
                    threshold_applied=0.363,
                    status="NO_SELFIE_PROVIDED",
                    message="Live presentation not submitted; document photo S-MAD morph analysis completed.",
                    morph_analysis=morph_res
                )
        except Exception as e:
            logger.warning(f"Face verify / morph detection warning for {scan_id}: {e}")

        # Extract holder name & document number
        holder_name = None
        if "name" in ocr_result.extracted_fields:
            holder_name = _get_field_value(ocr_result.extracted_fields["name"])
        elif "surname" in ocr_result.extracted_fields:
            holder_name = _get_field_value(ocr_result.extracted_fields["surname"])

        doc_number = None
        for id_key in ("passport_number", "document_number", "aadhaar_number", "pan_number", "dl_number", "epic_number", "visa_number"):
            if id_key in ocr_result.extracted_fields:
                val = _get_field_value(ocr_result.extracted_fields[id_key])
                if val:
                    doc_number = val
                    break

        # 5. Cross-Scan History Check (Requirement 4)
        _update_job(scan_id, stage="Checking Historical Screening Records & Identity Continuity...", progress=90)
        historical_check: Optional[Dict[str, Any]] = None
        db_hist = SessionLocal()
        try:
            curr_fields = {k: _get_field_value(v) for k, v in ocr_result.extracted_fields.items()}
            historical_check = check_scan_history(
                db=db_hist,
                document_number=doc_number,
                holder_name=holder_name,
                current_fields=curr_fields,
                current_scan_id=scan_id
            )
        except Exception as e:
            logger.warning(f"Cross-scan history check error for {scan_id}: {e}")
        finally:
            db_hist.close()

        # 6. Risk Scoring Engine (with non-dilution floor)
        _update_job(scan_id, stage="Calculating Transparent Risk Score & Final Assessment...", progress=95)
        risk_assessment: RiskAssessment = calculate_risk(
            ocr=ocr_result,
            validation=validation_result,
            tampering=tampering_result,
            biometrics=biometrics_result,
            historical_check=historical_check
        )

        # Save document file to disk for audit
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
                    scan_id=scan_id
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
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "officer_id": officer_id,
            "checkpoint": checkpoint,
            "document_type": ocr_result.document_type.value,
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
            "qr_verification": qr_verification,
        }
        report_dict = to_json_safe(report_dict)

        # Persist to database in worker thread
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
                scan_id=scan_id
            )
        finally:
            db.close()

        # Append to immutable screening_history table
        processing_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        _persist_to_screening_history(
            scan_id=scan_id,
            officer_id=officer_id,
            ocr_result=ocr_result,
            validation_result=validation_result,
            tampering_result=tampering_result,
            biometrics_result=biometrics_result,
            risk_assessment=risk_assessment,
            historical_check=historical_check,
            qr_verification=qr_verification,
            front_bytes=front_bytes,
            processing_time_ms=processing_time_ms,
            session_id=session_id,
            status=status,
        )

        # Mark job completed
        _update_job(
            scan_id,
            status="completed",
            stage="Screening Complete",
            progress=100,
            completed_at=datetime.utcnow().isoformat() + "Z",
            result=report_dict
        )
    except Exception as e:
        logger.error(f"Background screening error for {scan_id}: {e}", exc_info=True)
        _update_job(
            scan_id,
            status="failed",
            stage="Error",
            progress=100,
            completed_at=datetime.utcnow().isoformat() + "Z",
            error=str(e)
        )


# ---------------------------------------------------------------------------
# Polling Status Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/{scan_id}/status",
    response_model=ScanJobStatusResponse,
    summary="Poll Scan Execution Status",
    description="Check whether background scan has completed, failed, or is still processing."
)
async def get_scan_status(scan_id: str, db: Session = Depends(get_db)):
    job = _get_job(scan_id)
    if job:
        return ScanJobStatusResponse(**job)

    # Fallback to persistent DB record if memory cleared
    rec = get_scan_by_id(db, scan_id)
    if rec:
        return ScanJobStatusResponse(
            scan_id=rec.id,
            status="completed",
            stage="Archived in Database",
            progress=100,
            created_at=rec.created_at.isoformat() + "Z" if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
            completed_at=rec.created_at.isoformat() + "Z" if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
            result=rec.payload
        )

    raise HTTPException(status_code=404, detail=f"Scan record '{scan_id}' not found.")


# ---------------------------------------------------------------------------
# Core Screening Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/ocr",
    summary="Module 1 — OCR Field Extraction",
    description="Extract structured fields, checksums, and MRZ. Returns scan_id immediately or sync result."
)
async def scan_ocr_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Front document image"),
    document_type: str = Form("auto", description="Document type"),
    back_image: Optional[UploadFile] = File(None, description="Optional back-side image"),
    sync: bool = Form(False, description="Run synchronously if True (default False)")
):
    front_bytes = await _read_file_safe(file)
    if not front_bytes:
        raise HTTPException(status_code=400, detail="Front document image cannot be empty.")
    back_bytes = await _read_file_safe(back_image)

    # Synchronous mode
    if sync:
        try:
            result = await run_in_threadpool(extract_ocr, front_bytes, document_type, back_bytes)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR extraction failed: {str(e)}")

    # Asynchronous background mode
    today_str = datetime.utcnow().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    scan_id = f"SCAN-{today_str}-{short_uuid}"

    now_iso = datetime.utcnow().isoformat() + "Z"
    with _scan_jobs_lock:
        _SCAN_JOBS[scan_id] = {
            "scan_id": scan_id,
            "status": "processing",
            "stage": "Queued for OCR Processing",
            "progress": 15,
            "error": None,
            "created_at": now_iso,
            "completed_at": None,
            "result": None,
        }

    background_tasks.add_task(
        _run_ocr_background_worker,
        scan_id,
        front_bytes,
        document_type,
        back_bytes
    )

    return AsyncScanResponse(
        scan_id=scan_id,
        status="processing",
        stage="Queued for OCR Processing",
        progress=15,
        message="OCR extraction initiated in background"
    )


@router.post(
    "/full",
    summary="Full Orchestration — 4 Modules + Risk Engine + Persistence",
    description="Runs complete screening pipeline. Returns scan_id immediately for polling or synchronous report."
)
async def scan_full_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Front document image"),
    back_image: Optional[UploadFile] = File(None, description="Optional back image"),
    selfie_image: Optional[UploadFile] = File(None, description="Optional live portrait / selfie"),
    document_type: str = Form("auto", description="Document type or 'auto'"),
    officer_id: str = Form("OFFICER-4819", description="Officer station ID"),
    checkpoint: str = Form("Delhi IGI Airport (T3 Arrival)", description="Border checkpoint location"),
    session_id: Optional[str] = Form(None, description="Session ID linking documents screened together"),
    sync: bool = Form(False, description="Run synchronously if True (default False)"),
    db: Session = Depends(get_db)
):
    front_bytes = await _read_file_safe(file)
    if not front_bytes:
        raise HTTPException(status_code=400, detail="Front document image cannot be empty.")
    back_bytes = await _read_file_safe(back_image)
    selfie_bytes = await _read_file_safe(selfie_image)

    # Synchronous mode
    if sync:
        start_time = time.perf_counter()
        try:
            ocr_result = await run_in_threadpool(extract_ocr, front_bytes, document_type, back_bytes)
            validation_result = await run_in_threadpool(validate_document, ocr_result)
            flagged_field_keys = [k for k, v in validation_result.field_cross_validation.items() if v.flag]
            tampering_result = await run_in_threadpool(
                detect_tampering,
                front_bytes,
                ocr_result.document_type.value,
                flagged_field_keys
            )
            biometrics_result = None
            try:
                morph_res = await run_in_threadpool(detect_morphing, front_bytes)
                if selfie_bytes:
                    face_engine = get_face_engine()
                    biometrics_result = await run_in_threadpool(face_engine.verify, front_bytes, selfie_bytes)
                    biometrics_result.morph_analysis = morph_res
                else:
                    biometrics_result = FaceVerifyResult(
                        match=False,
                        confidence=0.0,
                        cosine_similarity=0.0,
                        l2_distance=999.0,
                        threshold_applied=0.363,
                        status="NO_SELFIE_PROVIDED",
                        message="Live presentation not submitted; document photo S-MAD morph analysis completed.",
                        morph_analysis=morph_res
                    )
            except Exception as e:
                logger.warning(f"Sync face verify / morph warning: {e}")

            holder_name = None
            if "name" in ocr_result.extracted_fields:
                holder_name = _get_field_value(ocr_result.extracted_fields["name"])
            elif "surname" in ocr_result.extracted_fields:
                holder_name = _get_field_value(ocr_result.extracted_fields["surname"])

            doc_number = None
            for id_key in ("passport_number", "document_number", "aadhaar_number", "pan_number", "dl_number", "epic_number", "visa_number"):
                if id_key in ocr_result.extracted_fields:
                    val = _get_field_value(ocr_result.extracted_fields[id_key])
                    if val:
                        doc_number = val
                        break

            today_str = datetime.utcnow().strftime("%Y%m%d")
            short_uuid = uuid.uuid4().hex[:6].upper()
            scan_id = f"SCAN-{today_str}-{short_uuid}"

            curr_fields = {k: _get_field_value(v) for k, v in ocr_result.extracted_fields.items()}
            historical_check = check_scan_history(
                db=db,
                document_number=doc_number,
                holder_name=holder_name,
                current_fields=curr_fields,
                current_scan_id=scan_id
            )

            risk_assessment = calculate_risk(
                ocr=ocr_result,
                validation=validation_result,
                tampering=tampering_result,
                biometrics=biometrics_result,
                historical_check=historical_check
            )

            if risk_assessment.risk_tier == "CRITICAL":
                status = "REJECTED"
            elif risk_assessment.risk_tier == "HIGH":
                status = "FLAGGED"
            elif risk_assessment.risk_tier == "MEDIUM":
                status = "MANUAL_REVIEW"
            else:
                status = "PASSED"

            # Append to immutable screening_history table
            processing_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            _persist_to_screening_history(
                scan_id=scan_id,
                officer_id=officer_id,
                ocr_result=ocr_result,
                validation_result=validation_result,
                tampering_result=tampering_result,
                biometrics_result=biometrics_result,
                risk_assessment=risk_assessment,
                historical_check=historical_check,
                qr_verification=None,
                front_bytes=front_bytes,
                processing_time_ms=processing_time_ms,
                session_id=session_id,
                status=status,
            )

            report_dict = {
                "scan_id": scan_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "officer_id": officer_id,
                "checkpoint": checkpoint,
                "document_type": ocr_result.document_type.value,
                "holder_name": holder_name,
                "document_number": doc_number,
                "risk": risk_assessment.model_dump(),
                "ocr": ocr_result.model_dump(),
                "validation": validation_result.model_dump(),
                "tampering": tampering_result.model_dump(),
                "biometrics": biometrics_result.model_dump() if biometrics_result else None,
                "document_image_url": None,
                "ela_heatmap_url": tampering_result.ela.heatmap_b64,
                "historical_check": historical_check
            }
            return FullScanReport(**report_dict)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Synchronous screening failed: {str(e)}")

    # Asynchronous mode (default)
    today_str = datetime.utcnow().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    scan_id = f"SCAN-{today_str}-{short_uuid}"
    now_iso = datetime.utcnow().isoformat() + "Z"

    with _scan_jobs_lock:
        _SCAN_JOBS[scan_id] = {
            "scan_id": scan_id,
            "status": "processing",
            "stage": "Queued for Forensic Screening",
            "progress": 10,
            "error": None,
            "created_at": now_iso,
            "completed_at": None,
            "result": None,
        }

    background_tasks.add_task(
        _run_full_scan_background_worker,
        scan_id,
        front_bytes,
        back_bytes,
        selfie_bytes,
        document_type,
        officer_id,
        checkpoint,
        session_id
    )

    return AsyncScanResponse(
        scan_id=scan_id,
        status="processing",
        stage="Queued for Forensic Screening",
        progress=10,
        message="Document screening queued in background"
    )


@router.post(
    "/validate",
    response_model=ValidationResult,
    summary="Module 2 — Document Validation",
    description="Validate extracted fields against document format standards, logical rules, and watchlists."
)
async def scan_validate_endpoint(payload: Dict[str, Any]):
    try:
        result = validate_document(payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")


@router.post(
    "/tampering",
    response_model=TamperingResult,
    summary="Module 3 — Tampering & Forgery Detection",
    description="Execute real Error Level Analysis (ELA), EXIF analysis, photo region splicing check, text font consistency, and stamp matching."
)
async def scan_tampering_endpoint(
    file: UploadFile = File(..., description="Document image to inspect for tampering")
):
    image_bytes = await _read_file_safe(file)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Document image cannot be empty.")

    try:
        result = await run_in_threadpool(detect_tampering, image_bytes)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tampering detection failed: {str(e)}")


@router.post(
    "/face-verify",
    summary="Module 4 — Biometric Face Verification + Liveness Detection",
    description=(
        "Verify passenger live presence and face-match against document photo. "
        "Accepts a short burst of frames (1.5-2 seconds) for liveness detection. "
        "Both liveness_passed and face_match must pass for overall verification. "
        "A high face-match score with failed liveness still FAILS overall. "
        "\n\n**Liveness challenge:** Randomly selected from: blink, turn_left, turn_right, smile. "
        "The frontend should request a frame burst after displaying the challenge instruction. "
        "\n\n**NOTE (Phase 1):** Software-based liveness using standard camera. Not equivalent to "
        "dedicated anti-spoofing hardware (IR/depth sensors). Iris biometrics are a future "
        "hardware-dependent enhancement requiring infrared iris-scanning cameras not present in this prototype."
    )
)
async def scan_face_verify_endpoint(
    doc_image: UploadFile = File(..., description="Document image containing holder photo"),
    selfie_image: Optional[UploadFile] = File(None, description="Single live frame (legacy mode)"),
    frame_0: Optional[UploadFile] = File(None, description="Liveness frame 0 (of burst)"),
    frame_1: Optional[UploadFile] = File(None, description="Liveness frame 1"),
    frame_2: Optional[UploadFile] = File(None, description="Liveness frame 2"),
    frame_3: Optional[UploadFile] = File(None, description="Liveness frame 3"),
    frame_4: Optional[UploadFile] = File(None, description="Liveness frame 4"),
    frame_5: Optional[UploadFile] = File(None, description="Liveness frame 5"),
    frame_6: Optional[UploadFile] = File(None, description="Liveness frame 6"),
    frame_7: Optional[UploadFile] = File(None, description="Liveness frame 7"),
    challenge: str = Form("blink", description="Liveness challenge: blink, turn_left, turn_right, smile"),
    threshold: float = Form(0.363, description="Cosine similarity match threshold (default 0.363)"),
    skip_liveness: bool = Form(False, description="Skip liveness check (legacy single-frame mode)")
):
    from ..modules.face_verification.liveness import analyze_liveness, YUNET_PATH

    doc_bytes = await _read_file_safe(doc_image)
    if not doc_bytes:
        raise HTTPException(status_code=400, detail="Document image is required.")

    # Collect frame burst
    frame_uploads = [frame_0, frame_1, frame_2, frame_3, frame_4, frame_5, frame_6, frame_7]
    frames_bytes: List[bytes] = []
    for fu in frame_uploads:
        fb = await _read_file_safe(fu)
        if fb:
            frames_bytes.append(fb)

    # Legacy single-frame mode fallback
    selfie_bytes = await _read_file_safe(selfie_image)
    if selfie_bytes and not frames_bytes:
        frames_bytes.append(selfie_bytes)

    if not frames_bytes:
        raise HTTPException(status_code=400, detail="At least one live frame is required.")

    # Use last frame as the selfie for face matching (most recent face position)
    selfie_for_match = frames_bytes[-1]

    try:
        engine = get_face_engine()

        # --- Step 1: Face Match ---
        face_result = await run_in_threadpool(engine.verify, doc_bytes, selfie_for_match, threshold)

        # --- Step 2: Liveness Detection ---
        liveness_result: Dict[str, Any] = {}
        if skip_liveness:
            liveness_result = {
                "liveness_passed": True,
                "liveness_score": 1.0,
                "challenge": challenge,
                "challenge_passed": True,
                "challenge_score": 1.0,
                "challenge_details": {"note": "Liveness check skipped (legacy mode)."},
                "texture_analysis": {},
                "frames_analyzed": len(frames_bytes),
                "faces_detected": 1,
                "fail_reason": None,
                "status": "SKIPPED",
            }
        else:
            liveness_result = await run_in_threadpool(
                analyze_liveness, frames_bytes, challenge, YUNET_PATH
            )

        liveness_passed = liveness_result.get("liveness_passed", False)
        liveness_score = liveness_result.get("liveness_score", 0.0)

        # --- Step 3: Face-Morphing Attack Detection (S-MAD) on Document Photo Only ---
        morph_result: MorphDetectionResult = await run_in_threadpool(detect_morphing, doc_bytes)
        face_result.morph_analysis = morph_result

        # Overall pass: BOTH face match AND liveness must pass.
        # Morph suspicion alerts officer with explainable signals without silently blocking match.
        overall_passed = face_result.match and liveness_passed

        # Determine human-readable verification summary according to explicit outcome
        match_pct = int(round(face_result.confidence * 100))
        if face_result.status == "NO_FACE_IN_DOCUMENT":
            summary_text = "No face detected in document image — try a clearer photo"
        elif face_result.status == "NO_FACE_IN_SELFIE":
            summary_text = "No face detected in live capture — please center your face in the oval"
        elif overall_passed and not morph_result.is_morph_suspected:
            summary_text = f"Biometric match verified ({match_pct}%). Identity and liveness confirmed."
        elif overall_passed and morph_result.is_morph_suspected:
            summary_text = f"Biometric match verified ({match_pct}%), but SUSPECTED FACE MORPHING ATTACK FLAGGED on document photo."
        elif not face_result.match:
            summary_text = f"{match_pct}% match — below threshold ({threshold}), recommend manual review"
        elif not liveness_passed:
            summary_text = f"Face match confirmed ({match_pct}%), but liveness verification failed: {liveness_result.get('fail_reason') or 'motion check failed'}."
        else:
            summary_text = "Biometric evaluation completed."

        # Build combined response
        response = {
            **face_result.model_dump(),
            "overall_verified": overall_passed,
            "liveness_passed": liveness_passed,
            "liveness_score": liveness_score,
            "liveness_challenge": challenge,
            "liveness_details": liveness_result,
            "morph_analysis": morph_result.model_dump(),
            "morph_suspicion_score": morph_result.morph_suspicion_score,
            "morph_suspicion_tier": morph_result.suspicion_tier,
            "is_morph_suspected": morph_result.is_morph_suspected,
            "morph_flags": morph_result.morph_flags,
            "verification_summary": summary_text,
        }
        return to_json_safe(response)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Face verification failed: {str(e)}")


@router.post(
    "/live-probe",
    summary="Module 4 — Real-time Live Camera Feature Probe & Dynamic Guidance",
    description=(
        "Analyzes a single live webcam frame for face fitting (fit in frame), "
        "head pose (yaw turn left/right), and facial expressions (smile/blink), "
        "returning instant telemetry and real-time checkpoint prompts."
    )
)
async def live_probe_endpoint(
    frame: UploadFile = File(..., description="Current live camera frame"),
    target_prompt: str = Form("fit_in_frame", description="Target prompt: fit_in_frame, turn_right, turn_left, smile, blink")
):
    from ..modules.face_verification.liveness import probe_single_frame, YUNET_PATH

    frame_bytes = await _read_file_safe(frame)
    if not frame_bytes:
        raise HTTPException(status_code=400, detail="Live frame image is required.")

    result = await run_in_threadpool(
        probe_single_frame, frame_bytes, target_prompt, YUNET_PATH
    )
    return result


