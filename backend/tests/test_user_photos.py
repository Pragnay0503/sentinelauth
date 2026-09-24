"""
test_user_photos.py - Integration tests on the 5 user-provided identity documents.
Tests real OCR extraction, document validation, tampering detection, and biometric matching.
"""
import os
import pytest
from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.document_validation.validator import validate_document
from backend.modules.tampering_detection.detector import detect_tampering
from backend.modules.face_verification.engine import get_face_engine
from backend.scoring.risk_engine import calculate_risk
from backend.db.database import SessionLocal, init_db
from backend.db.crud import create_scan_record, get_scan_by_id

SAMPLE_DIR = "public/samples"
THADA_FRONT = os.path.join(SAMPLE_DIR, "aadhaar_thada_front.png")
THADA_BACK = os.path.join(SAMPLE_DIR, "aadhaar_thada_back.jpg")
THADA_MERGED = os.path.join(SAMPLE_DIR, "aadhaar_thada_merged.png")
PAN_KAJA = os.path.join(SAMPLE_DIR, "pan_kaja.png")
SRIJA_AADHAAR = os.path.join(SAMPLE_DIR, "aadhaar_srija.png")


def test_user_aadhaar_thada_extraction():
    assert os.path.exists(THADA_FRONT), f"Test image {THADA_FRONT} must exist"
    with open(THADA_FRONT, "rb") as f:
        front_bytes = f.read()
    with open(THADA_BACK, "rb") as f:
        back_bytes = f.read()

    res = extract_ocr(front_bytes, "auto", back_bytes)
    assert "aadhaar" in str(res.document_type).lower()
    assert "2254 1472 0908" in res.extracted_fields.get("aadhaar_number").value
    assert "05/03/2007" in res.extracted_fields.get("date_of_birth").value
    assert "Male" in res.extracted_fields.get("gender").value
    assert "Sai Pragnay" in res.extracted_fields.get("name").value
    assert "Thada Srinivas Reddy" in res.extracted_fields.get("address").value


def test_user_pan_kaja_extraction():
    assert os.path.exists(PAN_KAJA), f"Test image {PAN_KAJA} must exist"
    with open(PAN_KAJA, "rb") as f:
        pan_bytes = f.read()

    res = extract_ocr(pan_bytes, "auto")
    assert "pan" in str(res.document_type).lower()
    assert res.extracted_fields.get("pan_number").value == "HRRPR5877P"
    assert "KAJA KARTHIKEYA REDDY" in res.extracted_fields.get("name").value
    assert "KAJA SRINIVASA REDDY" in res.extracted_fields.get("father_name").value
    assert "04/05/2007" in res.extracted_fields.get("date_of_birth").value


def test_user_srija_aadhaar_extraction():
    assert os.path.exists(SRIJA_AADHAAR), f"Test image {SRIJA_AADHAAR} must exist"
    with open(SRIJA_AADHAAR, "rb") as f:
        srija_bytes = f.read()

    res = extract_ocr(srija_bytes, "auto")
    assert "aadhaar" in str(res.document_type).lower()
    assert "4838 0779 9767" in res.extracted_fields.get("aadhaar_number").value
    assert "26/11/2006" in res.extracted_fields.get("date_of_birth").value
    assert "Female" in res.extracted_fields.get("gender").value
    assert "Padigela Srija" in res.extracted_fields.get("name").value


def test_user_photos_biometric_face_matching():
    engine = get_face_engine()
    
    # 1. Same subject (Thada front vs merged) -> should verify match
    res_same = engine.verify(THADA_FRONT, THADA_MERGED)
    assert res_same.match is True
    assert res_same.confidence >= 0.85

    # 2. Cross-subject (Thada vs Srija) -> should reject
    res_diff = engine.verify(THADA_FRONT, SRIJA_AADHAAR)
    assert res_diff.match is False
    assert res_diff.confidence < 0.60


def test_user_document_full_screening_and_persistence():
    init_db()
    db = SessionLocal()

    with open(THADA_FRONT, "rb") as f:
        doc_bytes = f.read()
    with open(THADA_MERGED, "rb") as f:
        selfie_bytes = f.read()

    ocr_res = extract_ocr(doc_bytes, "auto")
    val_res = validate_document(ocr_res)
    tamp_res = detect_tampering(doc_bytes)
    engine = get_face_engine()
    bio_res = engine.verify(doc_bytes, selfie_bytes)

    risk_res = calculate_risk(ocr_res, val_res, tamp_res, bio_res)
    assert risk_res.risk_score <= 30.0
    assert risk_res.risk_tier in ("LOW", "MEDIUM")

    # Verify persistence
    rec = create_scan_record(
        db=db,
        document_type=ocr_res.document_type.value,
        holder_name="Thada Sai Pragnay",
        document_number="2254 1472 0908",
        risk_score=risk_res.risk_score,
        risk_tier=risk_res.risk_tier,
        status="PASSED",
        validation_passed=val_res.is_valid,
        tampering_score=tamp_res.tampering_score,
        face_match_confidence=bio_res.confidence,
        officer_id="OFFICER-4819",
        checkpoint="Delhi IGI Airport (T3 Arrival)",
        payload={"risk": risk_res.model_dump()}
    )
    assert rec.id.startswith("SCAN-")
    fetched = get_scan_by_id(db, rec.id)
    assert fetched is not None
    assert fetched.holder_name == "Thada Sai Pragnay"
    db.close()
