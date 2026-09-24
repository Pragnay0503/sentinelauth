"""
test_serialization.py - Unit tests for universal NumPy JSON serialization & database persistence.
Tests:
1. to_json_safe conversion of numpy scalars (int64, float64, bool_) and numpy arrays.
2. NumpySafeEncoder custom JSON encoder fallback.
3. Database insertion into scan_records with numpy-infected payload.
4. End-to-end scan record creation on the real uploaded Aadhaar card (Kaja Karthikeya Reddy).
"""
import json
import os
import pytest
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.utils.serialization import to_json_safe, NumpySafeEncoder, safe_json_dumps
from backend.db.models import Base, ScanRecord
from backend.db.crud import create_scan_record, get_scan_by_id
from backend.db.database import SessionLocal


def test_to_json_safe_numpy_types():
    """Confirms to_json_safe converts all numpy scalars and arrays into native Python types."""
    raw_payload = {
        "int64_val": np.int64(42),
        "int32_val": np.int32(100),
        "float64_val": np.float64(3.14159),
        "float32_val": np.float32(2.718),
        "bool_val": np.bool_(True),
        "array_1d": np.array([1, 2, 3], dtype=np.int64),
        "array_2d": np.array([[1.1, 2.2], [3.3, 4.4]], dtype=np.float64),
        "nested": {
            "sub_int": np.int64(999),
            "sub_list": [np.float64(0.5), np.int64(12), np.bool_(False)],
        }
    }

    # Before to_json_safe, standard json.dumps MUST fail on np.int64
    with pytest.raises(TypeError):
        json.dumps(raw_payload)

    # After to_json_safe, standard json.dumps MUST succeed
    safe = to_json_safe(raw_payload)

    # Verify native python types
    assert type(safe["int64_val"]) is int
    assert safe["int64_val"] == 42
    assert type(safe["float64_val"]) is float
    assert abs(safe["float64_val"] - 3.14159) < 1e-4
    assert type(safe["bool_val"]) is bool
    assert safe["bool_val"] is True
    assert type(safe["array_1d"]) is list
    assert all(type(x) is int for x in safe["array_1d"])
    assert type(safe["nested"]["sub_int"]) is int
    assert type(safe["nested"]["sub_list"][0]) is float

    # Verify standard json.dumps succeeds and produces clean JSON
    serialized = json.dumps(safe)
    deserialized = json.loads(serialized)
    assert deserialized["int64_val"] == 42
    assert deserialized["nested"]["sub_int"] == 999


def test_numpy_safe_encoder():
    """Confirms NumpySafeEncoder serializes numpy objects even without manual to_json_safe."""
    raw_payload = {
        "score": np.float64(0.875),
        "count": np.int64(15),
        "flag": np.bool_(True),
        "matrix": np.array([10, 20, 30])
    }

    # Should serialize cleanly using custom encoder
    output = json.dumps(raw_payload, cls=NumpySafeEncoder)
    loaded = json.loads(output)
    assert loaded["score"] == 0.875
    assert loaded["count"] == 15
    assert loaded["flag"] is True
    assert loaded["matrix"] == [10, 20, 30]


def test_create_scan_record_with_numpy_payload():
    """Confirms create_scan_record sanitizes and commits payload with numpy values to SQLite without error."""
    db = SessionLocal()
    try:
        infected_payload = {
            "holder_name": "Kaja Karthikeya Reddy",
            "metrics": {
                "edge_count": np.int64(3),
                "laplacian_var": np.float64(22.45),
                "is_suspected": np.bool_(False),
                "histogram": np.array([1, 4, 9, 16], dtype=np.int64)
            }
        }

        record = create_scan_record(
            db=db,
            document_type="national_id_aadhaar",
            holder_name="Kaja Karthikeya Reddy",
            document_number="1234 5678 9012",
            risk_score=np.float64(45.0),
            risk_tier="MEDIUM",
            status="MANUAL_REVIEW",
            validation_passed=np.bool_(True),
            tampering_score=np.float64(0.197),
            face_match_confidence=np.float64(0.0),
            officer_id="OFFICER-4819",
            checkpoint="Hyderabad RGIA (T1 Int'l Arrival)",
            payload=infected_payload
        )

        assert record.id is not None
        fetched = get_scan_by_id(db, record.id)
        assert fetched is not None
        assert fetched.holder_name == "Kaja Karthikeya Reddy"
        assert fetched.payload["metrics"]["edge_count"] == 3
        assert fetched.payload["metrics"]["histogram"] == [1, 4, 9, 16]

    finally:
        db.close()


def test_kaja_karthikeya_reddy_full_pipeline_insert():
    """
    Re-runs the exact scan pipeline on the user's uploaded Aadhaar card (Kaja Karthikeya Reddy)
    and verifies that the scan record inserts and commits to scan_records cleanly.
    """
    img_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "uploads", "SCAN-20260912-40E496_doc.jpg"
    )
    if not os.path.exists(img_path):
        pytest.skip("Test upload image SCAN-20260912-40E496_doc.jpg not found.")

    with open(img_path, "rb") as f:
        front_bytes = f.read()

    from backend.modules.ocr_extraction.extractor import extract_ocr
    from backend.modules.document_validation.validator import validate_document
    from backend.modules.tampering_detection.detector import detect_tampering
    from backend.modules.face_verification.morph_detection import detect_morphing
    from backend.scoring.risk_engine import calculate_risk
    from backend.modules.face_verification.schemas import FaceVerifyResult

    # Execute all 4 pipeline stages
    ocr_result = extract_ocr(front_bytes, "national_id_aadhaar", None)
    validation_result = validate_document(ocr_result)
    flagged_keys = [k for k, v in validation_result.field_cross_validation.items() if v.flag]
    tampering_result = detect_tampering(front_bytes, document_type=ocr_result.document_type.value, flagged_fields=flagged_keys)
    morph_res = detect_morphing(front_bytes)

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

    risk_assessment = calculate_risk(
        ocr=ocr_result,
        validation=validation_result,
        tampering=tampering_result,
        biometrics=biometrics_result,
        historical_check=None
    )

    report_dict = {
        "document_type": ocr_result.document_type.value,
        "holder_name": "Kaja Karthikeya Reddy",
        "document_number": None,
        "risk": risk_assessment.model_dump(),
        "ocr": ocr_result.model_dump(),
        "validation": validation_result.model_dump(),
        "tampering": tampering_result.model_dump(),
        "biometrics": biometrics_result.model_dump(),
        "document_image_url": None,
        "ela_heatmap_url": tampering_result.ela.heatmap_b64,
        "historical_check": None
    }

    db = SessionLocal()
    try:
        rec = create_scan_record(
            db=db,
            document_type=ocr_result.document_type.value,
            holder_name="Kaja Karthikeya Reddy",
            document_number=None,
            risk_score=risk_assessment.risk_score,
            risk_tier=risk_assessment.risk_tier,
            status="MANUAL_REVIEW",
            validation_passed=validation_result.is_valid,
            tampering_score=tampering_result.tampering_score,
            face_match_confidence=0.0,
            officer_id="OFFICER-4819",
            checkpoint="Hyderabad RGIA (T1 Int'l Arrival)",
            payload=report_dict
        )

        assert rec.id is not None
        fetched = get_scan_by_id(db, rec.id)
        assert fetched is not None
        assert fetched.holder_name == "Kaja Karthikeya Reddy"
        assert fetched.payload is not None
        assert fetched.payload["holder_name"] == "Kaja Karthikeya Reddy"
        print(f"Successfully inserted scan record {rec.id} for Kaja Karthikeya Reddy!")
    finally:
        db.close()

