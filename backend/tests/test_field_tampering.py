"""
test_field_tampering.py — Test suite for single-field tampering detection:
  (a) Clean document: Low risk, no field flags.
  (b) Document with altered printed Date of Birth (visual != mrz):
      - Flags Date of Birth
      - mrz_checksum_valid: True
      - flag: VISUAL_MRZ_MISMATCH
      - Risk score not diluted (>= 65, HIGH tier)
  (c) Document with broken MRZ checksum on DOB:
      - Flags mrz_checksum_invalid on DOB specifically
  (d) Historical identity conflict check:
      - Discrepancy with past screening records
  (e) Localized field forensics:
      - Generates ELA anomaly, font consistency, and heatmap crop
"""
import pytest
import numpy as np
import cv2
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base
from backend.db.models import ScanRecord
from backend.db.crud import check_scan_history, create_scan_record
from backend.modules.document_validation.mrz_cross_validator import cross_validate_mrz_vs_visual
from backend.modules.document_validation.validator import validate_document
from backend.modules.tampering_detection.field_forensics import analyze_field_region, analyze_all_document_fields
from backend.modules.tampering_detection.detector import detect_tampering
from backend.modules.tampering_detection.schemas import (
    ELAResult, EXIFResult, PhotoTamperingResult, TextConsistencyResult, StampCheckResult, TamperingResult
)
from backend.modules.ocr_extraction.schemas import OCRResult, DocumentType, FieldResult, FieldSource
from backend.scoring.risk_engine import calculate_risk


# ---------------------------------------------------------------------------
# Helpers to build mock objects
# ---------------------------------------------------------------------------

def _mock_tampering_result(field_tampered: bool = False, tampered_field: str = "date_of_birth") -> TamperingResult:
    from backend.modules.tampering_detection.schemas import FieldForensicsResult
    field_forensics = {}
    if field_tampered:
        field_forensics[tampered_field] = FieldForensicsResult(
            ela_anomaly_score=0.74,
            font_consistency_score=0.42,
            likely_tampered=True,
            crop_ela_heatmap_b64="data:image/jpeg;base64,mockcrop"
        )
    return TamperingResult(
        tampering_score=0.60 if field_tampered else 0.10,
        is_tampered=field_tampered,
        confidence=0.90,
        ela=ELAResult(anomaly_score=0.15, mean_error=8.0, max_error=40.0, heatmap_b64="mock", flagged=False),
        exif=EXIFResult(has_exif=True, is_suspicious=False),
        photo_region=PhotoTamperingResult(photo_detected=True, noise_variance_ratio=1.05, ela_divergence=2.0, photo_splicing_detected=False, confidence=0.9),
        text_consistency=TextConsistencyResult(text_line_count=10, font_size_variance=2.0, baseline_alignment_variance=1.1, text_manipulation_suspected=False, confidence=0.9),
        stamp_seal=StampCheckResult(stamp_detected=True, match_score=0.85, edge_regularity=0.88, forgery_suspected=False),
        field_forensics=field_forensics,
        flagged_checks=["LOCALIZED_FIELD_TAMPERING"] if field_tampered else [],
        explanation=["Localized editing in DOB"] if field_tampered else ["Clean document"]
    )


# ---------------------------------------------------------------------------
# Case (a): Clean document
# ---------------------------------------------------------------------------

def test_case_a_clean_document():
    visual_fields = {
        "date_of_birth": "15/08/1985",
        "passport_number": "Z8833221",
        "name": "DOE JOHN",
        "gender": "M",
        "nationality": "IND",
        "date_of_expiry": "20/05/2030",
    }
    mrz_dict = {
        "dob": "15/08/1985",
        "doc_number": "Z8833221",
        "surname": "DOE",
        "given_names": "JOHN",
        "sex": "M",
        "nationality": "IND",
        "expiry": "20/05/2030",
    }

    mrz_checksums = {"dob": True, "doc_number": True, "expiry": True}

    # 1. Module 2 cross validation
    cross_res = cross_validate_mrz_vs_visual(visual_fields, mrz_dict, mrz_checksums)
    
    for f, item in cross_res.items():
        assert item.match is True, f"Field {f} should match"
        assert item.flag is None, f"Field {f} should have no flag"
        if item.mrz_checksum_valid is not None:
            assert item.mrz_checksum_valid is True

    # 2. Risk Engine
    ocr_res = OCRResult(
        document_type=DocumentType.passport,
        extracted_fields={k: FieldResult(value=v, confidence=0.98, source=FieldSource.both) for k, v in visual_fields.items()},
        visual_fields=visual_fields,
        mrz_parsed=mrz_dict,
        mrz_checksums=mrz_checksums,
        mrz_applicable=True,
        mrz_validation_passed=True
    )
    val_res = validate_document(ocr_res)
    assert val_res.is_valid is True
    assert len(val_res.violations) == 0

    tamper_res = _mock_tampering_result(field_tampered=False)
    risk = calculate_risk(ocr=ocr_res, validation=val_res, tampering=tamper_res)

    assert risk.risk_score <= 25.0, f"Expected clean score <= 25, got {risk.risk_score}"
    assert risk.risk_tier == "LOW"
    assert risk.operational_action == "CLEAR"


# ---------------------------------------------------------------------------
# Case (b): Document with altered printed Date of Birth (visual != mrz)
# ---------------------------------------------------------------------------

def test_case_b_altered_printed_dob():
    # Printed text was changed from 1983 to 1985, but MRZ remains authentic 1983 with valid check digit
    visual_fields = {
        "date_of_birth": "15/08/1985",
        "passport_number": "A1234567",
        "name": "DOE JOHN",
        "gender": "M",
        "nationality": "IND",
        "date_of_expiry": "20/05/2030",
    }
    mrz_dict = {
        "dob": "15/08/1983",      # Legitimate MRZ value
        "doc_number": "A1234567",
        "surname": "DOE",
        "given_names": "JOHN",
        "sex": "M",
        "nationality": "IND",
        "expiry": "20/05/2030",
    }
    mrz_checksums = {"dob": True, "doc_number": True, "expiry": True}

    # 1. Module 2 cross validation
    cross_res = cross_validate_mrz_vs_visual(visual_fields, mrz_dict, mrz_checksums)
    
    assert "date_of_birth" in cross_res
    dob_check = cross_res["date_of_birth"]
    assert dob_check.match is False
    assert dob_check.mrz_checksum_valid is True
    assert dob_check.flag == "VISUAL_MRZ_MISMATCH"
    assert dob_check.visual_value == "15/08/1985"
    assert dob_check.mrz_value == "15/08/1983"

    # 2. ValidationResult reflects violation
    ocr_res = OCRResult(
        document_type=DocumentType.passport,
        extracted_fields={k: FieldResult(value=v, confidence=0.98, source=FieldSource.visual) for k, v in visual_fields.items()},
        visual_fields=visual_fields,
        mrz_parsed=mrz_dict,
        mrz_checksums=mrz_checksums,
        mrz_applicable=True,
        mrz_validation_passed=True
    )
    val_res = validate_document(ocr_res)
    assert val_res.is_valid is False
    assert any("date_of_birth" in v.field for v in val_res.violations)

    # 3. Risk Engine Non-Dilution: Score must be at minimum 65 (HIGH tier), not diluted by clean fields!
    tamper_res = _mock_tampering_result(field_tampered=True, tampered_field="date_of_birth")
    risk = calculate_risk(ocr=ocr_res, validation=val_res, tampering=tamper_res)

    assert risk.risk_score >= 65.0, f"Expected non-diluted risk score >= 65.0, got {risk.risk_score}"
    assert risk.risk_tier in ("HIGH", "CRITICAL")
    assert risk.operational_action in ("SUPERVISOR_REVIEW", "INTERDICT_IMMEDIATE")

    # Explanation must specifically name the tampered field
    factor_descriptions = " ".join([f.description for f in risk.factors])
    assert "Date Of Birth" in factor_descriptions or "Date of Birth" in factor_descriptions
    assert "mismatch between printed value" in factor_descriptions or "localized image editing" in factor_descriptions


# ---------------------------------------------------------------------------
# Case (c): Document with broken MRZ checksum on DOB
# ---------------------------------------------------------------------------

def test_case_c_broken_mrz_checksum_on_dob():
    visual_fields = {
        "date_of_birth": "15/08/1985",
        "passport_number": "A1234567",
        "name": "DOE JOHN",
        "gender": "M",
    }
    mrz_dict = {
        "dob": "15/08/1985",
        "doc_number": "A1234567",
        "surname": "DOE",
        "given_names": "JOHN",
        "sex": "M",
    }
    # Check digit for DOB failed (tampered MRZ digits)
    mrz_checksums = {"dob": False, "doc_number": True, "expiry": True}

    cross_res = cross_validate_mrz_vs_visual(visual_fields, mrz_dict, mrz_checksums)
    
    assert "date_of_birth" in cross_res
    dob_check = cross_res["date_of_birth"]
    assert dob_check.mrz_checksum_valid is False
    assert dob_check.flag == "MRZ_CHECKSUM_INVALID"

    # ValidationResult
    ocr_res = OCRResult(
        document_type=DocumentType.passport,
        extracted_fields={k: FieldResult(value=v, confidence=0.98, source=FieldSource.both) for k, v in visual_fields.items()},
        visual_fields=visual_fields,
        mrz_parsed=mrz_dict,
        mrz_checksums=mrz_checksums,
        mrz_applicable=True,
        mrz_validation_passed=False
    )
    val_res = validate_document(ocr_res)
    assert any(v.field == "date_of_birth" and "MRZ check digit validation failed" in v.rule_violated for v in val_res.violations)


# ---------------------------------------------------------------------------
# Case (d): Cross-Scan History Check (DOB difference across scans)
# ---------------------------------------------------------------------------

def test_case_d_cross_scan_history_mismatch():
    # Setup test in-memory SQLite database
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    db = TestingSession()

    try:
        # Create prior scan record on 2024-01-15
        prior_record = ScanRecord(
            id="SCAN-20240115-HIST01",
            timestamp=datetime(2024, 1, 15, 10, 30),
            document_type="passport",
            holder_name="ALEXANDER VANDERBILT",
            document_number="A1234567",
            risk_score=12.0,
            risk_tier="LOW",
            status="PASSED",
            payload={
                "ocr": {
                    "extracted_fields": {
                        "name": {"value": "ALEXANDER VANDERBILT"},
                        "passport_number": {"value": "A1234567"},
                        "date_of_birth": {"value": "15/08/1983"},
                        "nationality": {"value": "GBR"},
                        "gender": {"value": "M"}
                    }
                }
            }
        )
        db.add(prior_record)
        db.commit()

        # Current scan arrives with altered DOB (15/08/1985)
        current_fields = {
            "name": "ALEXANDER VANDERBILT",
            "passport_number": "A1234567",
            "date_of_birth": "15/08/1985",
            "nationality": "GBR",
            "gender": "M"
        }

        hist_res = check_scan_history(
            db=db,
            document_number="A1234567",
            holder_name="ALEXANDER VANDERBILT",
            current_fields=current_fields,
            current_scan_id="SCAN-CURRENT-001"
        )

        assert hist_res["has_historical_match"] is True
        assert hist_res["matched_scan_id"] == "SCAN-20240115-HIST01"
        assert len(hist_res["mismatches"]) == 1
        mismatch = hist_res["mismatches"][0]
        assert mismatch["field"] == "date_of_birth"
        assert mismatch["current_value"] == "15/08/1985"
        assert mismatch["historical_value"] == "15/08/1983"
        assert "Date of Birth in this scan (15/08/1985) differs from previous scan on 2024-01-15 (15/08/1983)" in mismatch["message"]

        # Passing historical conflict to risk engine must push score >= 65
        ocr_res = OCRResult(
            document_type=DocumentType.passport,
            extracted_fields={k: FieldResult(value=v, confidence=0.98, source=FieldSource.visual) for k, v in current_fields.items()}
        )
        val_res = validate_document(ocr_res)
        tamper_res = _mock_tampering_result(field_tampered=False)

        risk = calculate_risk(
            ocr=ocr_res,
            validation=val_res,
            tampering=tamper_res,
            historical_check=hist_res
        )
        assert risk.risk_score >= 65.0, f"Expected risk >= 65 for historical mismatch, got {risk.risk_score}"
        assert risk.risk_tier in ("HIGH", "CRITICAL")
        assert any(f.category == "HISTORY" for f in risk.factors)

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Case (e): Localized Field Forensics Execution
# ---------------------------------------------------------------------------

def test_case_e_localized_field_forensics():
    # Create test document canvas
    img = np.ones((800, 1200, 3), dtype=np.uint8) * 240
    # Draw simulated fields
    cv2.putText(img, "PASSPORT", (400, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
    cv2.putText(img, "DOE JOHN", (260, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    cv2.putText(img, "15/08/1985", (260, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    cv2.putText(img, "INDIAN", (260, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)

    # Analyze field region for DOB
    dob_bbox = (0.49, 0.20, 0.63, 0.65)
    res = analyze_field_region(img, "dob", dob_bbox)
    
    assert 0.0 <= res.ela_anomaly_score <= 1.0
    assert 0.0 <= res.font_consistency_score <= 1.0
    assert isinstance(res.likely_tampered, bool)
    assert res.crop_ela_heatmap_b64.startswith("data:image/jpeg;base64,")

    # Analyze all document fields
    all_fields = analyze_all_document_fields(img, "passport")
    assert len(all_fields) > 0
    assert "dob" in all_fields or "date_of_birth" in all_fields
