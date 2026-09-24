"""
backend/tests/test_indian_id_extraction.py

Dedicated tests for Indian Government ID validations:
  1. PAN: Format regex, invalid variants, holder type decoding.
  2. Aadhaar: Verhoeff algorithm test vectors (2363/2364), UIDAI prefix/length rules.
  3. Voter ID: Modern format vs legacy non-matching format resilience.
  4. Sanity Check: Low-confidence but regex/format-valid flagging.
  5. End-to-End Extraction with specimen images.
  6. Aadhaar Name Latin script heuristic and candidate ranking.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_DIR = ROOT / "backend" / "data" / "sample_documents"


# ---------------------------------------------------------------------------
# 1. PAN Card Validation Tests
# ---------------------------------------------------------------------------

class TestPANValidation:
    def test_valid_pan_format(self):
        from backend.modules.ocr_extraction.checksums import validate_pan_format
        assert validate_pan_format("ABCDE1234F") is True

    def test_invalid_pan_lowercase(self):
        from backend.modules.ocr_extraction.checksums import validate_pan_format
        # Must strictly reject lowercase
        assert validate_pan_format("abcde1234f") is False

    def test_invalid_pan_wrong_length(self):
        from backend.modules.ocr_extraction.checksums import validate_pan_format
        # 9 chars
        assert validate_pan_format("ABCDE123F") is False
        # 11 chars
        assert validate_pan_format("ABCDE12345F") is False

    def test_invalid_pan_digit_in_letter_zone(self):
        from backend.modules.ocr_extraction.checksums import validate_pan_format
        # Digit at position 5
        assert validate_pan_format("ABCD11234F") is False
        # Letter in digit zone
        assert validate_pan_format("ABCDE12A4F") is False

    def test_pan_holder_type_decoding(self):
        from backend.modules.ocr_extraction.checksums import decode_pan_details
        # 'P' -> Individual
        p_res = decode_pan_details("ABCPE1234F")
        assert p_res["pan_format_valid"] is True
        assert p_res["pan_holder_type"] == "Individual"
        assert p_res["surname_initial"] == "E"

        # 'C' -> Company
        c_res = decode_pan_details("ABCCE1234F")
        assert c_res["pan_format_valid"] is True
        assert c_res["pan_holder_type"] == "Company"

        # 'H' -> HUF
        h_res = decode_pan_details("ABCHE1234F")
        assert h_res["pan_holder_type"] == "HUF"

        # Invalid format
        inv_res = decode_pan_details("invalid_pan")
        assert inv_res["pan_format_valid"] is False
        assert inv_res["pan_holder_type"] is None


# ---------------------------------------------------------------------------
# 2. Aadhaar & Verhoeff Algorithm Tests
# ---------------------------------------------------------------------------

class TestAadhaarValidation:
    def test_verhoeff_known_vector_2363(self):
        from backend.modules.ocr_extraction.checksums import validate_verhoeff
        # Standard known Verhoeff valid string
        assert validate_verhoeff("2363") is True

    def test_verhoeff_corrupted_vector_2364(self):
        from backend.modules.ocr_extraction.checksums import validate_verhoeff
        # Deliberately corrupted digit
        assert validate_verhoeff("2364") is False

    def test_aadhaar_first_digit_not_0_or_1(self):
        from backend.modules.ocr_extraction.checksums import validate_aadhaar_number, generate_verhoeff
        # Generate valid Verhoeff starting with 0
        zero_start = generate_verhoeff("01234567890")
        fmt_ok, chk_ok, reason = validate_aadhaar_number(zero_start)
        assert fmt_ok is False
        assert "cannot be 0 or 1" in str(reason)

        # Generate valid Verhoeff starting with 1
        one_start = generate_verhoeff("11234567890")
        fmt_ok, chk_ok, reason = validate_aadhaar_number(one_start)
        assert fmt_ok is False
        assert "cannot be 0 or 1" in str(reason)

    def test_aadhaar_12_digit_length_enforced(self):
        from backend.modules.ocr_extraction.checksums import validate_aadhaar_number
        # Too short
        fmt_ok, chk_ok, reason = validate_aadhaar_number("9999410567")
        assert fmt_ok is False
        assert "must be exactly 12 digits" in str(reason)

        # Too long
        fmt_ok, chk_ok, reason = validate_aadhaar_number("99994105678901")
        assert fmt_ok is False

    def test_aadhaar_valid_12_digits_passes(self):
        from backend.modules.ocr_extraction.checksums import validate_aadhaar_number, generate_verhoeff
        # Prefix starting with 9 (valid first digit)
        valid_12 = generate_verhoeff("99994105678")
        fmt_ok, chk_ok, reason = validate_aadhaar_number(valid_12)
        assert fmt_ok is True
        assert chk_ok is True
        assert reason is None

        # Formatted with spaces "9999 4105 678x"
        formatted = f"{valid_12[:4]} {valid_12[4:8]} {valid_12[8:]}"
        fmt_ok, chk_ok, reason = validate_aadhaar_number(formatted)
        assert fmt_ok is True
        assert chk_ok is True


# ---------------------------------------------------------------------------
# 3. Voter ID (EPIC) Tests
# ---------------------------------------------------------------------------

class TestVoterIDValidation:
    def test_modern_epic_format(self):
        from backend.modules.ocr_extraction.checksums import validate_epic_format
        assert validate_epic_format("ABC1234567") is True
        assert validate_epic_format("WBD9876543") is True
        # Lowercase should not match standard
        assert validate_epic_format("abc1234567") is False

    def test_legacy_format_soft_failure_does_not_crash(self):
        from backend.modules.ocr_extraction.checksums import validate_epic_format
        from backend.modules.ocr_extraction.field_extractor import extract_fields
        # Legacy non-standard state voter ID string
        legacy_id = "DL/01/001/000123"
        assert validate_epic_format(legacy_id) is False

        # Mock image
        dummy_img = np.zeros((200, 400, 3), dtype=np.uint8)
        mock_raw = f"ELECTION COMMISSION OF INDIA\nELECTOR'S NAME: RAMESH GUPTA\nEPIC NO: {legacy_id}\nAGE: 42\nGENDER: MALE"

        with patch("backend.modules.ocr_extraction.field_extractor.extract_raw_text", return_value=(mock_raw, [("EPIC", 0.9)])):
            fields, text, meta = extract_fields(dummy_img, "national_id_voter")
            assert meta.get("anchor_found") is True
            assert fields.get("epic_number")[0] == legacy_id




# ---------------------------------------------------------------------------
# 5. Confidence vs Regex-Match Sanity Check Tests
# ---------------------------------------------------------------------------

class TestConfidenceSanityCheck:
    def test_low_confidence_but_format_valid_triggers_flag(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr

        dummy_img = np.zeros((200, 400, 3), dtype=np.uint8)
        # Mock visual fields where PAN number is valid but confidence is only 0.45 (< 0.6)
        mock_fields = {
            "pan_number": ("ABCDE1234F", 0.45),
            "name": ("TEST USER", 0.9),
        }
        mock_text = "INCOME TAX DEPARTMENT GOVT OF INDIA PERMANENT ACCOUNT NUMBER ABCDE1234F"
        mock_meta = {"anchor_found": True}

        with patch("backend.modules.ocr_extraction.extractor.preprocess_image", return_value=dummy_img), \
             patch("backend.modules.ocr_extraction.extractor.extract_fields", return_value=(mock_fields, mock_text, mock_meta)):
            result = extract_ocr(dummy_img, "national_id_pan")
            assert result.checksum_validation.get("pan_format_valid") is True
            assert result.low_confidence_but_format_valid is True
            assert result.checksum_validation.get("low_confidence_but_format_valid") is True


# ---------------------------------------------------------------------------
# 6. End-to-End Specimen Extraction
# ---------------------------------------------------------------------------

class TestSpecimenExtraction:
    def test_specimen_pan_card(self):
        from backend.modules.ocr_extraction.extractor import extract_ocr
        pan_path = SAMPLE_DIR / "specimen_pan_card.png"
        if not pan_path.exists():
            pytest.skip("Specimen PAN card not found")

        raw_bytes = pan_path.read_bytes()
        result = extract_ocr(raw_bytes, "national_id_pan")
        assert result.document_type.value == "national_id_pan"
        assert result.checksum_validation.get("pan_format_valid") is True
        assert len(result.extracted_fields) > 0
        assert "pan_number" in result.extracted_fields


# ---------------------------------------------------------------------------
# 7. Aadhaar Name Latin Heuristic & Debug Logging Regression Tests
# ---------------------------------------------------------------------------

class TestAadhaarNameLatinRegression:
    def test_stacked_multilingual_text_selects_latin_name(self):
        """
        Multilingual Aadhaar card test:
        Stacked text contains regional script (Hindi), OCR misread artifact ('POD FERD'),
        and correct Latin name ('SUNITA SHARMA') directly above DOB.
        Must select 'SUNITA SHARMA' and reject 'POD FERD'.
        """
        from backend.modules.ocr_extraction.field_extractor import (
            _evaluate_aadhaar_name_candidates,
            _extract_aadhaar_fields,
        )

        sample_text = (
            "भारत सरकार\n"
            "GOVERNMENT OF INDIA\n"
            "पोड फेर्ड\n"
            "POD FERD\n"
            "SUNITA SHARMA\n"
            "DOB: 15/08/1992\n"
            "Female\n"
            "9999 4105 6788\n"
        )
        dummy_raw = [(line, 0.95) for line in sample_text.splitlines()]

        best_name, debug_info = _evaluate_aadhaar_name_candidates(sample_text, dummy_raw)
        assert best_name == "SUNITA SHARMA"

        # Check candidate debug info
        candidates_map = {c["candidate"]: c for c in debug_info if "candidate" in c}
        assert "SUNITA SHARMA" in candidates_map
        assert candidates_map["SUNITA SHARMA"]["selected"] is True
        assert candidates_map["SUNITA SHARMA"]["latin_ratio"] >= 0.85

        # Check that POD FERD was not selected and was penalized/rejected
        if "POD FERD" in candidates_map:
            assert candidates_map["POD FERD"]["selected"] is False
            assert candidates_map["POD FERD"]["score"] < candidates_map["SUNITA SHARMA"]["score"]

        # Run via _extract_aadhaar_fields
        fields, debug_list = _extract_aadhaar_fields(sample_text, dummy_raw)
        assert fields["name"][0] == "SUNITA SHARMA"
        assert fields["gender"][0] == "Female"
        assert fields["date_of_birth"][0] == "15/08/1992"
        assert fields["aadhaar_number"][0] == "9999 4105 6788"

