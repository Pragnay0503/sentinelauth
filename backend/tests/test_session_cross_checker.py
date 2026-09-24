"""
test_session_cross_checker.py - Unit and integration tests for cross-document validation
and 3-document session report generation (Passport + Aadhaar + Driving Licence).
"""
import json
import os
import sys
import unittest
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.modules.document_validation.cross_document_validator import (
    normalize_fields,
    cross_validate_session_documents,
    _names_are_consistent,
    _dobs_are_consistent,
)
from backend.utils.serialization import to_json_safe


class TestNormalizeFields(unittest.TestCase):
    def test_normalize_passport_fields(self):
        passport_raw = {
            "surname": "REDDY",
            "given_names": "KAJA KARTHIKEYA",
            "passport_number": "M1234567",
            "dob": "2000-05-15",
            "nationality": "INDIAN",
            "sex": "M",
        }
        canonical = normalize_fields(passport_raw, document_type="passport")
        self.assertEqual(canonical["name"], "KAJA KARTHIKEYA REDDY")
        self.assertEqual(canonical["document_number"], "M1234567")
        self.assertEqual(canonical["date_of_birth"], "2000-05-15")
        self.assertEqual(canonical["nationality"], "INDIAN")
        self.assertEqual(canonical["gender"], "M")
        self.assertIsNone(canonical["address"])

    def test_normalize_aadhaar_fields(self):
        aadhaar_raw = {
            "name": "Kaja Karthikeya Reddy",
            "aadhaar_number": "1234 5678 9012",
            "dob": "15/05/2000",
            "gender": "Male",
            "address": "Plot 42, Jubilee Hills, Hyderabad, Telangana 500033",
        }
        canonical = normalize_fields(aadhaar_raw, document_type="national_id_aadhaar")
        self.assertEqual(canonical["name"], "Kaja Karthikeya Reddy")
        self.assertEqual(canonical["document_number"], "1234 5678 9012")
        self.assertEqual(canonical["date_of_birth"], "15/05/2000")
        self.assertEqual(canonical["gender"], "Male")
        self.assertIn("Hyderabad", canonical["address"])

    def test_normalize_driving_license_fields(self):
        dl_raw = {
            "name": "KARTHIKEYA REDDY KAJA",
            "dl_number": "DL-0420110012345",
            "date_of_birth": "2000-05-15",
            "expiry": "2035-05-14",
            "address": None,
        }
        canonical = normalize_fields(dl_raw, document_type="driving_license")
        self.assertEqual(canonical["name"], "KARTHIKEYA REDDY KAJA")
        self.assertEqual(canonical["document_number"], "DL-0420110012345")
        self.assertEqual(canonical["date_of_birth"], "2000-05-15")
        self.assertIsNone(canonical["address"])


class TestCrossDocumentComparison(unittest.TestCase):
    def test_name_consistency_variations(self):
        self.assertTrue(_names_are_consistent("KAJA KARTHIKEYA REDDY", "KARTHIKEYA REDDY KAJA"))
        self.assertTrue(_names_are_consistent("Kaja Karthikeya Reddy", "KAJA KARTHIKEYA REDDY"))
        self.assertTrue(_names_are_consistent("KARTHIKEYA REDDY", "KAJA KARTHIKEYA REDDY"))
        self.assertFalse(_names_are_consistent("KAJA KARTHIKEYA REDDY", "VIKRAM SHARMA"))

    def test_dob_consistency_variations(self):
        self.assertTrue(_dobs_are_consistent("2000-05-15", "15/05/2000"))
        self.assertTrue(_dobs_are_consistent("2000-05-15", "15-05-2000"))
        self.assertTrue(_dobs_are_consistent("2000", "2000-05-15"))  # YOB match
        self.assertFalse(_dobs_are_consistent("2000-05-15", "1995-05-15"))

    def test_three_document_session_passport_aadhaar_dl(self):
        """
        The user exact scenario:
        1. Passport: name, dob, passport_number
        2. Aadhaar: name, dob, aadhaar_number, address
        3. Driving Licence: transposed name, dob, dl_number, NO address
        """
        scans = [
            {
                "scan_id": "SCAN-001",
                "document_type": "passport",
                "document_label": "Passport",
                "scan_payload": {
                    "name": "KAJA KARTHIKEYA REDDY",
                    "dob": "2000-05-15",
                    "passport_number": "M1234567",
                    "nationality": "IND",
                },
            },
            {
                "scan_id": "SCAN-002",
                "document_type": "national_id_aadhaar",
                "document_label": "Aadhaar Card",
                "scan_payload": {
                    "name": "Kaja Karthikeya Reddy",
                    "dob": "15/05/2000",
                    "aadhaar_number": "123456789012",
                    "address": "Hyderabad, Telangana",
                },
            },
            {
                "scan_id": "SCAN-003",
                "document_type": "driving_license",
                "document_label": "Driving Licence",
                "scan_payload": {
                    "name": "KARTHIKEYA REDDY KAJA",
                    "dob": "2000-05-15",
                    "dl_number": "DL-0420110012345",
                },
            },
        ]

        result = cross_validate_session_documents(scans)

        self.assertFalse(result["has_cross_document_mismatch"])
        self.assertEqual(len(result["mismatched_fields"]), 0)
        self.assertGreater(result["corroboration_factor"], 0.0)

        # Name check
        name_fc = result["field_consistency"].get("name")
        self.assertIsNotNone(name_fc)
        self.assertTrue(name_fc["consistent"])
        self.assertTrue(name_fc["match"])
        self.assertEqual(name_fc["status"], "verified_consistent")
        self.assertEqual(len(name_fc["values"]), 3)

        # DOB check
        dob_fc = result["field_consistency"].get("date_of_birth")
        self.assertIsNotNone(dob_fc)
        self.assertTrue(dob_fc["consistent"])
        self.assertTrue(dob_fc["match"])
        self.assertEqual(dob_fc["status"], "verified_consistent")
        self.assertEqual(len(dob_fc["values"]), 3)

        # Address check: Only Aadhaar had address, DL and Passport did not
        addr_fc = result["field_consistency"].get("address")
        self.assertIsNotNone(addr_fc)
        self.assertIsNone(addr_fc["consistent"])
        self.assertIsNone(addr_fc["match"])
        self.assertEqual(addr_fc["status"], "insufficient_corroboration")
        self.assertEqual(addr_fc["reason"], "insufficient_documents_with_field")
        self.assertIsNone(addr_fc["flag"])

        # Document number: Should NOT be cross-compared or flagged as mismatch
        self.assertNotIn("document_number", result["field_consistency"])

        # Verify JSON serializability
        serialized = json.dumps(result)
        self.assertIn("verified_consistent", serialized)

    def test_cross_document_mismatch_fires_when_dob_differs(self):
        scans = [
            {
                "scan_id": "SCAN-001",
                "document_type": "passport",
                "scan_payload": {"name": "KAJA KARTHIKEYA REDDY", "dob": "2000-05-15"},
            },
            {
                "scan_id": "SCAN-002",
                "document_type": "national_id_aadhaar",
                "scan_payload": {"name": "KAJA KARTHIKEYA REDDY", "dob": "2000-05-15"},
            },
            {
                "scan_id": "SCAN-003",
                "document_type": "driving_license",
                "scan_payload": {"name": "KAJA KARTHIKEYA REDDY", "dob": "1995-01-01"},  # Differing DOB
            },
        ]
        result = cross_validate_session_documents(scans)
        self.assertTrue(result["has_cross_document_mismatch"])
        self.assertIn("date_of_birth", result["mismatched_fields"])
        self.assertIn("CROSS_DOCUMENT_MISMATCH", result["flags"])

    def test_numpy_int64_payload_serialization(self):
        """Verify numpy scalar types in scan payloads do not crash validation or serialization."""
        scans = [
            {
                "scan_id": "SCAN-001",
                "document_type": "passport",
                "scan_payload": {
                    "name": "KAJA KARTHIKEYA REDDY",
                    "dob": "2000-05-15",
                    "int_metric": np.int64(42),
                    "float_metric": np.float64(3.1415),
                    "bool_metric": np.bool_(True),
                },
            },
            {
                "scan_id": "SCAN-002",
                "document_type": "driving_license",
                "scan_payload": {
                    "name": "KAJA KARTHIKEYA REDDY",
                    "dob": "2000-05-15",
                    "int_metric": np.int64(100),
                },
            },
        ]
        result = cross_validate_session_documents(scans)
        # Should not throw TypeError
        dumped = json.dumps(result)
        self.assertIsInstance(dumped, str)


if __name__ == "__main__":
    unittest.main()
