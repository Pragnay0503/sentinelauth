"""
test_risk_engine.py - Unit tests for the explainable risk scoring formulas and tier logic.
"""
import pytest
from backend.scoring.risk_engine import calculate_risk
from backend.modules.ocr_extraction.schemas import OCRResult, DocumentType
from backend.modules.document_validation.schemas import ValidationResult, Violation, Severity
from backend.modules.tampering_detection.schemas import (
    TamperingResult, ELAResult, EXIFResult, PhotoTamperingResult,
    TextConsistencyResult, StampCheckResult
)
from backend.modules.face_verification.schemas import FaceVerifyResult


def _make_dummy_tampering(score=0.10, is_tampered=False):
    return TamperingResult(
        tampering_score=score,
        is_tampered=is_tampered,
        confidence=0.9,
        ela=ELAResult(anomaly_score=score, mean_error=15.0, max_error=120.0, heatmap_b64="data:image/jpeg;base64,abc", flagged=False),
        exif=EXIFResult(has_exif=True, software_detected=None, editing_tools_found=[], is_suspicious=False),
        photo_region=PhotoTamperingResult(photo_detected=True, noise_variance_ratio=1.0, ela_divergence=5.0, photo_splicing_detected=False, confidence=0.9),
        text_consistency=TextConsistencyResult(text_line_count=5, font_size_variance=2.0, baseline_alignment_variance=1.5, text_manipulation_suspected=False, confidence=0.9),
        stamp_seal=StampCheckResult(stamp_detected=True, match_score=0.9, edge_regularity=0.8, forgery_suspected=False),
        flagged_checks=[],
        explanation=["Authentic forensics verified"]
    )


def test_clean_document_low_risk():
    ocr = OCRResult(document_type=DocumentType.passport, raw_ocr_text="SAMPLE TEXT")
    val = ValidationResult(is_valid=True, validation_score=100.0, violations=[], warnings=[])
    tamp = _make_dummy_tampering(score=0.08)
    bio = FaceVerifyResult(
        match=True, confidence=0.95, cosine_similarity=0.85, l2_distance=0.4,
        threshold_applied=0.363, status="SUCCESS"
    )

    assessment = calculate_risk(ocr, val, tamp, bio)
    assert assessment.risk_score <= 25.0
    assert assessment.risk_tier == "LOW"
    assert assessment.operational_action == "CLEAR"
    assert len(assessment.factors) == 0
    assert len(assessment.clear_factors) > 0


def test_watchlist_hit_triggers_critical_risk():
    ocr = OCRResult(document_type=DocumentType.passport, raw_ocr_text="VIKRAM SHARMA")
    val = ValidationResult(
        is_valid=False,
        is_blacklisted=True,
        validation_score=0.0,
        violations=[Violation(field="holder_name", rule_violated="Watchlist entry matched", severity="CRITICAL")],
        details={"blacklist_entry": {"category": "STOLEN_PASSPORT", "reason": "Interpol SLTD match"}}
    )
    tamp = _make_dummy_tampering(score=0.10)
    bio = None

    assessment = calculate_risk(ocr, val, tamp, bio)
    assert assessment.risk_score >= 81.0
    assert assessment.risk_tier == "CRITICAL"
    assert assessment.operational_action == "INTERDICT_IMMEDIATE"
    assert any(f.category == "WATCHLIST" for f in assessment.factors)


def test_tampering_and_biometric_mismatch_elevates_score():
    ocr = OCRResult(document_type=DocumentType.national_id_aadhaar, raw_ocr_text="TEXT")
    val = ValidationResult(is_valid=True, validation_score=90.0, violations=[])
    tamp = _make_dummy_tampering(score=0.65, is_tampered=True)
    tamp.flagged_checks = ["HIGH_COMPRESSION_ANOMALY", "PHOTO_REPLACEMENT_SUSPECTED"]
    bio = FaceVerifyResult(
        match=False, confidence=0.25, cosine_similarity=0.10, l2_distance=1.2,
        threshold_applied=0.363, status="SUCCESS"
    )

    assessment = calculate_risk(ocr, val, tamp, bio)
    assert assessment.risk_score > 40.0
    assert assessment.risk_tier in ("MEDIUM", "HIGH", "CRITICAL")
    assert any(f.category == "TAMPERING" for f in assessment.factors)
    assert any(f.category == "BIOMETRICS" for f in assessment.factors)
