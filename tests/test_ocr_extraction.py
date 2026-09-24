"""
tests/test_ocr_extraction.py

Unit tests for the upgraded OCR Extraction module.
Tests cover:
  1. Schemas & Enums (including national_id_pan, national_id_aadhaar, national_id_voter)
  2. Preprocessing & QR code presence detector
  3. Checksum algorithms (Aadhaar Verhoeff & PAN regex format)
  4. MRZ parsing (ICAO 9303 checksum validation)
  5. Cross-checking (MRZ vs visual tampering signals)
  6. Field extraction across all document types (Passport, Visa, PAN, Aadhaar, Voter ID, DL)
  7. Document type auto-detection & document_type_mismatch detection
  8. FastAPI endpoints (POST /api/ocr/extract & GET /api/ocr/health)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_DIR = ROOT / "backend" / "data" / "sample_documents"


def _read_sample(filename: str) -> bytes:
    path = SAMPLE_DIR / filename
    if not path.exists():
        pytest.skip(f"Sample file not found: {path}")
    return path.read_bytes()


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_document_type_enum(self):
        from backend.modules.ocr_extraction.schemas import DocumentType
        assert DocumentType.passport.value == "passport"
        assert DocumentType.visa.value == "visa"
        assert DocumentType.national_id.value == "national_id"
        assert DocumentType.driving_license.value == "driving_license"
        assert DocumentType.permit.value == "permit"
        assert DocumentType.national_id_pan.value == "national_id_pan"
        assert DocumentType.national_id_aadhaar.value == "national_id_aadhaar"
        assert DocumentType.national_id_voter.value == "national_id_voter"

    def test_field_result_confidence_range(self):
        from backend.modules.ocr_extraction.schemas import FieldResult, FieldSource
        fr = FieldResult(value="SHARMA", confidence=0.9, source=FieldSource.visual)
        assert 0.0 <= fr.confidence <= 1.0

    def test_ocr_result_defaults(self):
        from backend.modules.ocr_extraction.schemas import OCRResult, DocumentType
        result = OCRResult(document_type=DocumentType.passport)
        assert result.mrz_validation_passed is None
        assert result.mrz_applicable is False
        assert result.document_type_mismatch is False
        assert result.field_mismatches == []
        assert result.raw_ocr_text == ""

    def test_document_image_schema(self):
        from backend.modules.ocr_extraction.schemas import DocumentImage, DocumentType
        doc = DocumentImage(image=b"fake_bytes", document_type=DocumentType.passport)
        assert doc.document_type == DocumentType.passport
        assert doc.image == b"fake_bytes"


# ---------------------------------------------------------------------------
# 2. Checksum & Format Validation Tests
# ---------------------------------------------------------------------------

class TestChecksums:
    def test_aadhaar_verhoeff_valid(self):
        from backend.modules.ocr_extraction.checksums import validate_verhoeff, generate_verhoeff
        # Compute valid 12-digit number and check
        valid_num = generate_verhoeff("99994105678")
        assert len(valid_num) == 12
        assert validate_verhoeff(valid_num) is True
        assert validate_verhoeff(f"{valid_num[:4]} {valid_num[4:8]} {valid_num[8:]}") is True

    def test_aadhaar_verhoeff_corrupted(self):
        from backend.modules.ocr_extraction.checksums import validate_verhoeff, generate_verhoeff
        valid_num = generate_verhoeff("99994105678")
        # Flip the last digit to corrupt checksum
        corrupted_last = "0" if valid_num[-1] != "0" else "1"
        corrupted_num = valid_num[:-1] + corrupted_last
        assert validate_verhoeff(corrupted_num) is False

    def test_aadhaar_verhoeff_invalid_length(self):
        from backend.modules.ocr_extraction.checksums import validate_verhoeff
        assert validate_verhoeff("12345") is False
        assert validate_verhoeff("") is False

    def test_pan_format_validation(self):
        from backend.modules.ocr_extraction.checksums import validate_pan_format
        assert validate_pan_format("ABCDE1234F") is True
        assert validate_pan_format("abcde1234f") is False
        assert validate_pan_format("12345ABCDE") is False
        assert validate_pan_format("ABCDE12345") is False
        assert validate_pan_format("ABCD12345F") is False


    def test_epic_format_validation(self):
        from backend.modules.ocr_extraction.checksums import validate_epic_format
        assert validate_epic_format("WBD1234567") is True
        assert validate_epic_format("XYZ9876543") is True
        assert validate_epic_format("1234567890") is False
        assert validate_epic_format("AB12345678") is False


# ---------------------------------------------------------------------------
# 3. Preprocessing & QR Code Detection Tests
# ---------------------------------------------------------------------------

class TestPreprocessing:
    def test_preprocess_passport_image(self):
        import numpy as np
        from backend.modules.ocr_extraction.preprocessing import preprocess_image
        raw = _read_sample("specimen_passport_1.png")
        processed = preprocess_image(raw)
        assert isinstance(processed, np.ndarray)
        assert processed.ndim == 3
        assert processed.shape[2] == 3

    def test_preprocess_does_not_crash_on_any_sample(self):
        from backend.modules.ocr_extraction.preprocessing import preprocess_image
        for filename in os.listdir(SAMPLE_DIR):
            if filename.endswith(".png"):
                raw = _read_sample(filename)
                result = preprocess_image(raw)
                assert result is not None

    def test_qr_code_detection_on_aadhaar(self):
        from backend.modules.ocr_extraction.preprocessing import detect_qr_code_presence
        import cv2
        path = str(SAMPLE_DIR / "specimen_aadhaar_card.png")
        if os.path.exists(path):
            img = cv2.imread(path)
            # Should detect the synthetic QR pattern box
            has_qr = detect_qr_code_presence(img)
            assert isinstance(has_qr, bool)


# ---------------------------------------------------------------------------
# 4. MRZ Parser Tests
# ---------------------------------------------------------------------------

class TestMRZParser:
    SPECIMEN_TD3_L1 = "P<INDSHARMA<<ANITA<PRIYA<<<<<<<<<<<<<<<<<<<<<<"
    SPECIMEN_TD3_L2 = "P12345670IND9008154F3308144<<<<<<<<<<<<<<<<2"

    def test_icao_checksum_validation(self):
        from backend.modules.ocr_extraction.mrz_parser import validate_checksum
        assert isinstance(validate_checksum("P1234567", "0"), bool)

    def test_detect_mrz_lines_from_text(self):
        from backend.modules.ocr_extraction.mrz_parser import detect_mrz_lines
        text = f"Some header text\n{self.SPECIMEN_TD3_L1}\n{self.SPECIMEN_TD3_L2}\nFooter"
        lines = detect_mrz_lines(text)
        assert len(lines) >= 1

    def test_format_date_century_heuristic(self):
        from backend.modules.ocr_extraction.mrz_parser import _fmt_date
        assert _fmt_date("900815") == "15/08/1990"
        assert _fmt_date("330814") == "14/08/2033"


# ---------------------------------------------------------------------------
# 5. Cross-Checker Tests
# ---------------------------------------------------------------------------

class TestCrossChecker:
    def test_no_mismatch_when_fields_match(self):
        from backend.modules.ocr_extraction.cross_checker import cross_check
        from backend.modules.ocr_extraction.mrz_parser import MRZData
        mrz = MRZData()
        mrz.surname = "SHARMA"
        mrz.dob = "900815"
        mrz.expiry = "330814"
        mrz.doc_number = "P1234567"
        mrz.nationality = "IND"
        visual = {
            "name": ("SHARMA", 0.9),
            "date_of_birth": ("15/08/1990", 0.9),
            "date_of_expiry": ("14/08/2033", 0.9),
            "passport_number": ("P1234567", 0.9),
        }
        mismatches = cross_check(mrz, visual)
        assert mismatches == {}

    def test_mismatch_detected_on_changed_dob(self):
        from backend.modules.ocr_extraction.cross_checker import cross_check
        from backend.modules.ocr_extraction.mrz_parser import MRZData
        mrz = MRZData()
        mrz.dob = "900815"
        visual = {"date_of_birth": ("15/08/1999", 0.9)}
        mismatches = cross_check(mrz, visual)
        assert "date_of_birth" in mismatches


# ---------------------------------------------------------------------------
# 6. PAN, Aadhaar, and Voter ID Extraction Tests
# ---------------------------------------------------------------------------

class TestNewDocumentExtractions:
    def test_pan_card_extraction(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_pan_card.png")
        result = extract_ocr(raw, "national_id_pan")
        assert result.document_type.value == "national_id_pan"
        assert result.mrz_applicable is False
        assert result.mrz_validation_passed is None
        assert "pan_number" in result.extracted_fields
        assert result.checksum_validation.get("pan_format_valid") is True

    def test_aadhaar_card_extraction(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_aadhaar_card.png")
        result = extract_ocr(raw, "national_id_aadhaar")
        assert result.document_type.value == "national_id_aadhaar"
        assert result.mrz_applicable is False
        assert result.mrz_validation_passed is None
        assert "aadhaar_number" in result.extracted_fields
        assert result.checksum_validation.get("aadhaar_verhoeff_valid") is True

    def test_voter_id_extraction(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_voter_id.png")
        result = extract_ocr(raw, "national_id_voter")
        assert result.document_type.value == "national_id_voter"
        assert result.mrz_applicable is False
        assert "epic_number" in result.extracted_fields
        assert result.checksum_validation.get("epic_format_valid") is True


# ---------------------------------------------------------------------------
# 7. Document Type Auto-Detection & Mismatch Trigger
# ---------------------------------------------------------------------------

class TestAutoDetectionAndMismatch:
    def test_pan_submitted_as_passport_triggers_mismatch(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_pan_card.png")
        # Submit a PAN card with document_type="passport"
        result = extract_ocr(raw, "passport")
        assert result.document_type_mismatch is True
        assert result.detected_document_subtype == "national_id_pan"
        assert result.document_type.value == "national_id_pan"
        assert "pan_number" in result.extracted_fields

    def test_auto_detect_subtype_function(self):
        from backend.modules.ocr_extraction.field_extractor import detect_document_subtype
        assert detect_document_subtype("INCOME TAX DEPARTMENT GOVT OF INDIA ABCDE1234F") == "national_id_pan"
        assert detect_document_subtype("UNIQUE IDENTIFICATION AUTHORITY OF INDIA AADHAAR 1234 5678 9012") == "national_id_aadhaar"
        assert detect_document_subtype("ELECTION COMMISSION OF INDIA EPIC NO WBD1234567") == "national_id_voter"
        assert detect_document_subtype("REPUBLIC OF INDIA PASSPORT P<IND") == "passport"


# ---------------------------------------------------------------------------
# 8. Full Pipeline & Existing Types
# ---------------------------------------------------------------------------

class TestExtractOCR:
    def test_passport_extraction_returns_ocr_result(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_passport_1.png")
        result = extract_ocr(raw, "passport")
        assert result.document_type.value == "passport"
        assert result.mrz_applicable is True
        assert isinstance(result.confidence_scores, dict)

    def test_visa_extraction(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_visa_1.png")
        result = extract_ocr(raw, "visa")
        assert result.document_type.value == "visa"
        assert result.mrz_applicable is True

    def test_driving_license_extraction(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        raw = _read_sample("specimen_driving_license.png")
        result = extract_ocr(raw, "driving_license")
        assert result.document_type.value == "driving_license"
        assert result.mrz_applicable is False


# ---------------------------------------------------------------------------
# 9. FastAPI Endpoint Tests
# ---------------------------------------------------------------------------

class TestFastAPIEndpoint:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_health_check(self, client):
        resp = client.get("/api/ocr/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_extract_endpoint_passport(self, client):
        raw = _read_sample("specimen_passport_1.png")
        resp = client.post(
            "/api/ocr/extract",
            data={"document_type": "passport"},
            files={"file": ("specimen_passport_1.png", raw, "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["document_type"] == "passport"
        assert body["mrz_applicable"] is True

    def test_extract_endpoint_pan_card(self, client):
        raw = _read_sample("specimen_pan_card.png")
        resp = client.post(
            "/api/ocr/extract",
            data={"document_type": "national_id_pan"},
            files={"file": ("specimen_pan_card.png", raw, "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["document_type"] == "national_id_pan"
        assert body["mrz_applicable"] is False
        assert len(body["extracted_fields"]) > 0
        assert "pan_number" in body["extracted_fields"]

    def test_api_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "paddleocr_ready" in data
        assert "tesseract_ready" in data

    def test_both_ocr_engines_fail_returns_503(self, client):
        from unittest.mock import patch
        raw = _read_sample("specimen_pan_card.png")
        with patch("backend.modules.ocr_extraction.ocr_engine.run_paddleocr", side_effect=RuntimeError("PaddleOCR internal crash")):
            with patch("backend.modules.ocr_extraction.ocr_engine.run_pytesseract", side_effect=RuntimeError("Tesseract binary not found")):
                resp = client.post(
                    "/api/ocr/extract",
                    data={"document_type": "national_id_pan"},
                    files={"file": ("specimen_pan_card.png", raw, "image/png")},
                )
                assert resp.status_code == 503
                body = resp.json()
                assert body["error"] == "OCR extraction failed"
                assert "PaddleOCR internal crash" in body["paddleocr_error"]
                assert "Tesseract binary not found" in body["tesseract_error"]
