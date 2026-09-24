"""
test_auto_classify_and_validation.py - Comprehensive verification of:
1. Image-level auto-classification (Passport, Aadhaar, PAN, DL).
2. Type mismatch warning generation when submitted tab != detected type.
3. Analysis routed strictly to detected document type.
4. Valid-only checks for each document type (Passport MRZ/ICAO, Aadhaar Verhoeff/QR, PAN 5th-char surname match).
5. Uncarried fields marked as 'not applicable for this document type'.
"""
import os
import sys
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.modules.ocr_extraction.field_extractor import (
    detect_document_subtype,
    extract_fields,
    CARRIED_FIELDS_BY_DOC_TYPE,
    DOC_TYPE_DISPLAY_NAMES,
)
from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.document_validation.rules_engine import (
    validate_pan_rules,
    validate_aadhaar_rules,
    validate_passport_rules,
    validate_dl_rules,
)
from backend.modules.document_validation.validator import validate_document
from backend.modules.document_validation.cross_document_validator import cross_validate_session_documents


class TestAutoClassifyAndValidation(unittest.TestCase):

    # =========================================================================
    # 1. Document Auto-Classification
    # =========================================================================
    def test_classify_passport_mrz_td3(self):
        text = (
            "PASSPORT REPUBLIC OF INDIA\n"
            "GIVEN NAME: ARYAN SURNAME: THADA\n"
            "P<INDTHADA<<ARYAN<<<<<<<<<<<<<<<<<<<<<<<<<<<\n"
            "Z1234567<4IND9501014M2501019<<<<<<<<<<<<<<06\n"
        )
        detected = detect_document_subtype(text)
        self.assertEqual(detected, "passport")

    def test_classify_aadhaar_uidai_bilingual(self):
        text = (
            "भारत सरकार GOVERNMENT OF INDIA\n"
            "मेरा आधार, मेरी पहचान\n"
            "Thada Aryan\n"
            "DOB: 15/08/1995\n"
            "Male\n"
            "5486 9821 3240\n"
            "UIDAI QR CODE DATA\n"
        )
        detected = detect_document_subtype(text)
        self.assertEqual(detected, "national_id_aadhaar")

    def test_classify_pan_income_tax(self):
        text = (
            "INCOME TAX DEPARTMENT\n"
            "GOVT. OF INDIA\n"
            "Permanent Account Number Card\n"
            "ABCDE1234F\n"
            "Name: ARYAN THADA\n"
            "Father's Name: SURESH THADA\n"
            "DOB: 15/08/1995\n"
        )
        detected = detect_document_subtype(text)
        self.assertEqual(detected, "national_id_pan")

    def test_classify_driving_licence_state_rto(self):
        text = (
            "UNION OF INDIA DRIVING LICENCE\n"
            "TELANGANA STATE TRANSPORT DEPARTMENT\n"
            "DL NO: TS09 20180012345\n"
            "DOB: 15/08/1995\n"
            "Name: ARYAN THADA\n"
            "COV: LMV, MCWG\n"
        )
        detected = detect_document_subtype(text)
        self.assertEqual(detected, "driving_license")

    # =========================================================================
    # 2. Type Mismatch Warning & Dynamic Pipeline Routing
    # =========================================================================
    @patch("backend.modules.ocr_extraction.extractor.load_and_downscale")
    def test_type_mismatch_warning_passport_tab_with_aadhaar_doc(self, mock_load):
        dummy_img = np.ones((300, 400, 3), dtype=np.uint8) * 255
        mock_load.return_value = (dummy_img, 1.0, 5)

        raw_aadhaar_text = (
            "भारत सरकार GOVERNMENT OF INDIA\n"
            "Mera Aadhaar Meri Pehchan\n"
            "Thada Aryan\n"
            "DOB: 15/08/1995\n"
            "Male\n"
            "5486 9821 3240\n"
        )

        with patch("backend.modules.ocr_extraction.extractor.preprocess_image", return_value=(dummy_img, 0.0, 5)):
            with patch("backend.modules.ocr_extraction.ocr_engine.extract_raw_text", return_value=(raw_aadhaar_text, [])):
                result = extract_ocr(
                    image=b"fake_image_bytes",
                    document_type="passport"  # Tab was set to Passport
                )

        # Verify detected subtype is Aadhaar
        self.assertEqual(result.detected_document_subtype, "national_id_aadhaar")
        # Verify warning is generated with exact required format
        self.assertIsNotNone(result.type_mismatch_warning)
        self.assertEqual(
            result.type_mismatch_warning,
            "Type mismatch — tab set to Passport, document detected as Aadhaar. Analysing as Aadhaar."
        )
        # Verify analysis was routed to Aadhaar (Aadhaar number extracted, not passport number)
        doc_num = result.extracted_fields.get("document_number")
        self.assertIsNotNone(doc_num)
        self.assertEqual(doc_num.value.replace(" ", ""), "548698213240")
        # Verify Aadhaar Verhoeff checksum was run
        self.assertIn("aadhaar_verhoeff_valid", result.checksum_validation)
        # Verify uncarried fields for Aadhaar are marked as not applicable
        self.assertEqual(result.visual_fields.get("date_of_expiry"), "not applicable for this document type")
        self.assertEqual(result.visual_fields.get("nationality"), "not applicable for this document type")

    @patch("backend.modules.ocr_extraction.extractor.load_and_downscale")
    def test_type_mismatch_warning_pan_tab_with_dl_doc(self, mock_load):
        dummy_img = np.ones((300, 400, 3), dtype=np.uint8) * 255
        mock_load.return_value = (dummy_img, 1.0, 5)

        raw_dl_text = (
            "INDIAN UNION DRIVING LICENCE\n"
            "DL NO: TS09 20180012345\n"
            "Name: ARYAN THADA\n"
            "DOB: 15/08/1995\n"
        )

        with patch("backend.modules.ocr_extraction.extractor.preprocess_image", return_value=(dummy_img, 0.0, 5)):
            with patch("backend.modules.ocr_extraction.ocr_engine.extract_raw_text", return_value=(raw_dl_text, [])):
                result = extract_ocr(
                    image=b"fake_image_bytes",
                    document_type="national_id_pan"  # Tab was set to PAN
                )

        self.assertEqual(result.detected_document_subtype, "driving_license")
        self.assertEqual(
            result.type_mismatch_warning,
            "Type mismatch — tab set to PAN, document detected as Driving Licence. Analysing as Driving Licence."
        )
        # Verify DL RTO format validation was executed
        self.assertIn("rto_format_valid", result.checksum_validation)
        self.assertTrue(result.checksum_validation["rto_format_valid"])

    # =========================================================================
    # 3. PAN 5th-Character Surname Match
    # =========================================================================
    def test_pan_surname_match_success(self):
        # Surname THADA -> Initial 'T'. PAN: ABCPT1234F -> 5th character 'T' -> Match!
        fields = {
            "pan_number": "ABCPT1234F",
            "name": "ARYAN THADA",
            "date_of_birth": "15/08/1995",
        }
        violations = validate_pan_rules(fields)
        surname_violations = [v for v in violations if v.field == "pan_surname_match"]
        self.assertEqual(len(surname_violations), 0)

    def test_pan_surname_match_failure(self):
        # Surname SHARMA -> Initial 'S'. PAN: ABCPK1234F -> 5th character 'K' -> Mismatch!
        fields = {
            "pan_number": "ABCPK1234F",
            "name": "VIKRAM SHARMA",
            "date_of_birth": "15/08/1995",
        }
        violations = validate_pan_rules(fields)
        surname_violations = [v for v in violations if v.field == "pan_surname_match"]
        self.assertEqual(len(surname_violations), 1)
        self.assertIn("surname match failed", surname_violations[0].rule_violated)

    # =========================================================================
    # 4. Aadhaar Verhoeff Checksum & QR Verification
    # =========================================================================
    def test_aadhaar_verhoeff_rules(self):
        # 548698213240 has valid Verhoeff checksum
        fields = {
            "aadhaar_number": "548698213240",
            "name": "Thada Aryan",
            "date_of_birth": "15/08/1995",
        }
        violations = validate_aadhaar_rules(fields)
        verhoeff_violations = [v for v in violations if "Verhoeff" in v.rule_violated]
        self.assertEqual(len(verhoeff_violations), 0)

        # Invalid checksum
        fields_bad = {
            "aadhaar_number": "548698213249",
            "name": "Thada Aryan",
            "date_of_birth": "15/08/1995",
        }
        violations_bad = validate_aadhaar_rules(fields_bad)
        verhoeff_violations_bad = [v for v in violations_bad if "Verhoeff" in v.rule_violated]
        self.assertEqual(len(verhoeff_violations_bad), 1)

    # =========================================================================
    # 5. Non-Applicable Fields Marked Distinctly (Never Missing)
    # =========================================================================
    def test_uncarried_fields_marked_not_applicable_for_aadhaar(self):
        val_res = validate_document({
            "document_type": "national_id_aadhaar",
            "extracted_fields": {
                "document_number": "548698213240",
                "name": "Thada Aryan",
                "date_of_birth": "15/08/1995",
            }
        })
        self.assertEqual(val_res.details.get("extracted_expiry"), "not applicable for this document type")
        self.assertEqual(val_res.details.get("extracted_nationality"), "not applicable for this document type")
        self.assertFalse(val_res.is_expired)  # Aadhaar cannot be marked expired

    def test_uncarried_fields_marked_not_applicable_for_pan(self):
        val_res = validate_document({
            "document_type": "national_id_pan",
            "extracted_fields": {
                "document_number": "ABCPT1234F",
                "name": "Aryan Thada",
                "date_of_birth": "15/08/1995",
            }
        })
        self.assertEqual(val_res.details.get("extracted_expiry"), "not applicable for this document type")
        self.assertEqual(val_res.details.get("extracted_nationality"), "not applicable for this document type")
        self.assertFalse(val_res.is_expired)

    def test_cross_document_validation_ignores_not_applicable_fields(self):
        scans = [
            {
                "scan_id": "S1",
                "document_type": "passport",
                "document_label": "Passport",
                "scan_payload": {
                    "name": "Aryan Thada",
                    "dob": "1995-08-15",
                    "nationality": "IND",
                }
            },
            {
                "scan_id": "S2",
                "document_type": "national_id_pan",
                "document_label": "PAN Card",
                "scan_payload": {
                    "name": "Aryan Thada",
                    "dob": "1995-08-15",
                    "nationality": "not applicable for this document type",
                }
            }
        ]
        res = cross_validate_session_documents(scans)
        # Nationality was only in 1 document (Passport) because PAN marked it not applicable
        nat_fc = res["field_consistency"].get("nationality")
        self.assertIsNotNone(nat_fc)
        self.assertIn("PAN Card", nat_fc.get("not_applicable_documents", []))
        # Should NOT trigger false mismatch!
        self.assertFalse(res["has_cross_document_mismatch"])


if __name__ == "__main__":
    unittest.main()
