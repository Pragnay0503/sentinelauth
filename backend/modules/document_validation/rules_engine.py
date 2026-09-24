"""
rules_engine.py — Per-document-type validators, logical consistency checks,
and Module 1 red-flag ingest for Module 2 Document Validation.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schemas import Severity, Violation
from ..ocr_extraction.checksums import is_masked_aadhaar

# =========================================================
# COUNTRY FORMATS CONFIG
# =========================================================

_COUNTRY_FORMATS: Dict[str, Any] = {}

def _load_country_formats() -> Dict[str, Any]:
    """Load country_formats.json from data/ directory."""
    global _COUNTRY_FORMATS
    if _COUNTRY_FORMATS:
        return _COUNTRY_FORMATS
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "country_formats.json",
        Path(__file__).resolve().parent.parent.parent / "data" / "country_formats.json",
        Path("data") / "country_formats.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    _COUNTRY_FORMATS = json.load(f)
                break
            except (json.JSONDecodeError, IOError):
                pass
    return _COUNTRY_FORMATS


# =========================================================
# MRZ CHECKSUM RE-VERIFICATION (ICAO 9303)
# =========================================================

_MRZ_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MRZ_WEIGHTS = [7, 3, 1]


def _mrz_char_value(ch: str) -> int:
    """Return numeric value for MRZ check digit calculation."""
    if ch == "<" or ch == " ":
        return 0
    idx = _MRZ_CHARSET.find(ch.upper())
    return idx if idx >= 0 else 0


def compute_mrz_check_digit(data: str) -> int:
    """Compute ICAO 9303 Modulo 10 check digit with weights [7, 3, 1]."""
    total = 0
    for i, ch in enumerate(data):
        total += _mrz_char_value(ch) * _MRZ_WEIGHTS[i % 3]
    return total % 10


def verify_mrz_checksums(mrz_line1: str, mrz_line2: str) -> List[Violation]:
    """Re-verify MRZ check digits for TD3 (passport) format."""
    violations: List[Violation] = []
    if not mrz_line1 or not mrz_line2:
        return violations

    line1 = mrz_line1.strip().upper()
    line2 = mrz_line2.strip().upper()

    if len(line2) < 44:
        return violations  # Not a valid TD3 MRZ line 2

    # Document number: chars 0-8, check digit at char 9
    doc_num = line2[0:9]
    doc_check = line2[9]
    if doc_check.isdigit():
        expected = compute_mrz_check_digit(doc_num)
        if int(doc_check) != expected:
            violations.append(Violation(
                field="mrz_document_number_checksum",
                rule_violated=f"MRZ document number checksum mismatch: expected {expected}, got {doc_check}",
                severity=Severity.CRITICAL.value,
            ))

    # Date of birth: chars 13-18, check digit at char 19
    dob = line2[13:19]
    dob_check = line2[19]
    if dob_check.isdigit():
        expected = compute_mrz_check_digit(dob)
        if int(dob_check) != expected:
            violations.append(Violation(
                field="mrz_dob_checksum",
                rule_violated=f"MRZ date of birth checksum mismatch: expected {expected}, got {dob_check}",
                severity=Severity.CRITICAL.value,
            ))

    # Date of expiry: chars 21-26, check digit at char 27
    expiry = line2[21:27]
    expiry_check = line2[27]
    if expiry_check.isdigit():
        expected = compute_mrz_check_digit(expiry)
        if int(expiry_check) != expected:
            violations.append(Violation(
                field="mrz_expiry_checksum",
                rule_violated=f"MRZ expiry date checksum mismatch: expected {expected}, got {expiry_check}",
                severity=Severity.CRITICAL.value,
            ))

    return violations


# =========================================================
# GENDER ENUM VALIDATION
# =========================================================

_VALID_GENDERS = {"MALE", "FEMALE", "TRANSGENDER", "M", "F", "X", "OTHER"}


def validate_gender(fields: Dict[str, Any]) -> List[Violation]:
    """Validate gender field is a recognized enum value."""
    violations: List[Violation] = []
    gender = extract_field_value(fields, "gender", "sex")
    if gender:
        clean = gender.strip().upper()
        if clean not in _VALID_GENDERS:
            violations.append(Violation(
                field="gender",
                rule_violated=f"Invalid gender value: '{gender}' (expected one of: Male, Female, Transgender, M, F, X)",
                severity=Severity.MEDIUM.value,
            ))
    return violations


# =========================================================
# AGE PLAUSIBILITY CHECK
# =========================================================

def validate_age_plausibility(fields: Dict[str, Any]) -> List[Violation]:
    """Check that person's age at document issue is plausible (5-120 years)."""
    violations: List[Violation] = []
    dob_str = extract_field_value(fields, "date_of_birth", "dob")
    issue_str = extract_field_value(fields, "date_of_issue", "issue_date")

    dob = parse_date(dob_str)
    if not dob:
        return violations

    reference = parse_date(issue_str) or datetime.date.today()
    age_years = (reference - dob).days / 365.25

    if age_years < 5:
        violations.append(Violation(
            field="age_plausibility",
            rule_violated=f"Implausible age: person would be ~{int(age_years)} years old at document issue (under 5)",
            severity=Severity.HIGH.value,
        ))
    elif age_years > 120:
        violations.append(Violation(
            field="age_plausibility",
            rule_violated=f"Implausible age: person would be ~{int(age_years)} years old at document issue (over 120)",
            severity=Severity.HIGH.value,
        ))

    return violations


# =========================================================
# COUNTRY-SPECIFIC PASSPORT FORMAT VALIDATION
# =========================================================

def validate_passport_country_format(passport_number: str, nationality: Optional[str]) -> List[Violation]:
    """Validate passport number against country-specific regex from country_formats.json."""
    violations: List[Violation] = []
    if not passport_number or not nationality:
        return violations

    formats = _load_country_formats()
    if not formats:
        return violations

    # Map nationality text to country code
    nationality_to_code = {
        "INDIAN": "IN", "INDIA": "IN", "IND": "IN",
        "AMERICAN": "US", "USA": "US", "UNITED STATES": "US",
        "BRITISH": "GB", "GBR": "GB", "UNITED KINGDOM": "GB",
        "CANADIAN": "CA", "CANADA": "CA", "CAN": "CA",
        "AUSTRALIAN": "AU", "AUSTRALIA": "AU", "AUS": "AU",
        "FRENCH": "FR", "FRANCE": "FR", "FRA": "FR",
        "GERMAN": "DE", "GERMANY": "DE", "DEU": "DE",
        "EMIRATI": "AE", "UAE": "AE", "ARE": "AE",
        "SINGAPOREAN": "SG", "SINGAPORE": "SG", "SGP": "SG",
        "CHINESE": "CN", "CHINA": "CN", "CHN": "CN",
        "NIGERIAN": "NG", "NIGERIA": "NG", "NGA": "NG",
    }

    nat_upper = nationality.strip().upper()
    country_code = nationality_to_code.get(nat_upper, nat_upper[:2] if len(nat_upper) <= 3 else None)

    if country_code and country_code in formats:
        country_data = formats[country_code]
        passport_pattern = country_data.get("passport")
        if passport_pattern:
            clean = re.sub(r"[^A-Z0-9]", "", passport_number.upper())
            if not re.match(passport_pattern, clean):
                country_name = country_data.get("country_name", country_code)
                violations.append(Violation(
                    field="passport_number",
                    rule_violated=f"Passport number '{passport_number}' does not match {country_name} format pattern ({passport_pattern})",
                    severity=Severity.MEDIUM.value,
                ))

    return violations

_MONTHS = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}


def extract_field_value(fields: Dict[str, Any], *candidate_keys: str) -> Optional[str]:
    """
    Look up a field value in extracted_fields using candidate keys.
    Handles FieldResult objects, dictionaries, and raw strings.
    """
    if not fields:
        return None

    normalized_map = {}
    for k, v in fields.items():
        norm_k = re.sub(r"[^a-z0-9]", "", str(k).lower())
        normalized_map[norm_k] = v

    for candidate in candidate_keys:
        norm_cand = re.sub(r"[^a-z0-9]", "", str(candidate).lower())
        if norm_cand in normalized_map:
            val = normalized_map[norm_cand]
            if hasattr(val, "value"):
                res = str(val.value).strip()
            elif isinstance(val, dict):
                res = str(val.get("value", "")).strip()
            else:
                res = str(val).strip()

            if res and res.lower() not in ("not detected", "none", "null", ""):
                return res

    return None


def parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Parse varied date formats into datetime.date."""
    if not date_str:
        return None
    clean = str(date_str).strip().upper()
    if clean in ("NOT DETECTED", "NONE", "NULL", ""):
        return None

    # 1. DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m1 = re.match(r"^(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{4})$", clean)
    if m1:
        d, m, y = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
        try:
            return datetime.date(y, m, d)
        except ValueError:
            return None

    # 2. YYYY-MM-DD or YYYY/MM/DD
    m2 = re.match(r"^(\d{4})[/\.-](\d{1,2})[/\.-](\d{1,2})$", clean)
    if m2:
        y, m, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        try:
            return datetime.date(y, m, d)
        except ValueError:
            return None

    # 3. DD MMM YYYY (e.g. 14 AUG 1992, 14-AUG-1992)
    m3 = re.match(r"^(\d{1,2})[\s/\.-]([A-Z]{3,9})[\s/\.-](\d{4})$", clean)
    if m3:
        d = int(m3.group(1))
        m_str = m3.group(2)
        y = int(m3.group(3))
        m = _MONTHS.get(m_str)
        if m:
            try:
                return datetime.date(y, m, d)
            except ValueError:
                return None

    # 4. YOB fallback (YYYY)
    m4 = re.match(r"^(\d{4})$", clean)
    if m4:
        y = int(m4.group(1))
        if 1900 <= y <= 2100:
            return datetime.date(y, 1, 1)

    return None


def check_date_consistency(
    dob_str: Optional[str],
    issue_date_str: Optional[str],
    expiry_date_str: Optional[str],
    today: Optional[datetime.date] = None,
) -> Tuple[List[Violation], bool]:
    """
    Verify logical consistency across dates:
      1. date_of_birth < date_of_issue < date_of_expiry
      2. Expiry not in the past (flags is_expired)
      3. DOB and issue date cannot be in the future
    """
    violations: List[Violation] = []
    is_expired = False
    now = today or datetime.date.today()

    dob = parse_date(dob_str)
    issue = parse_date(issue_date_str)
    expiry = parse_date(expiry_date_str)

    # 1. DOB checks
    if dob:
        if dob > now:
            violations.append(
                Violation(
                    field="date_of_birth",
                    rule_violated=f"Date of birth cannot be in the future: {dob_str}",
                    severity=Severity.CRITICAL.value,
                )
            )
        if dob.year < 1900:
            violations.append(
                Violation(
                    field="date_of_birth",
                    rule_violated=f"Date of birth is unrealistically old (pre-1900): {dob_str}",
                    severity=Severity.HIGH.value,
                )
            )

    # 2. Issue date checks
    if issue:
        if issue > now:
            violations.append(
                Violation(
                    field="date_of_issue",
                    rule_violated=f"Date of issue cannot be in the future: {issue_date_str}",
                    severity=Severity.HIGH.value,
                )
            )

    # 3. Expiry date checks
    if expiry:
        if expiry < now:
            is_expired = True
            violations.append(
                Violation(
                    field="date_of_expiry",
                    rule_violated=f"Document has expired on {expiry_date_str} (prior to current date {now})",
                    severity=Severity.CRITICAL.value,
                )
            )

    # 4. Cross-date order checks: DOB < Issue < Expiry
    if dob and issue:
        if dob >= issue:
            violations.append(
                Violation(
                    field="date_consistency",
                    rule_violated=f"Date of birth ({dob_str}) must precede date of issue ({issue_date_str})",
                    severity=Severity.CRITICAL.value,
                )
            )

    if issue and expiry:
        if issue >= expiry:
            violations.append(
                Violation(
                    field="date_consistency",
                    rule_violated=f"Date of issue ({issue_date_str}) must precede date of expiry ({expiry_date_str})",
                    severity=Severity.CRITICAL.value,
                )
            )

    if dob and expiry:
        if dob >= expiry:
            violations.append(
                Violation(
                    field="date_consistency",
                    rule_violated=f"Date of birth ({dob_str}) must precede date of expiry ({expiry_date_str})",
                    severity=Severity.CRITICAL.value,
                )
            )

    return violations, is_expired


def check_visa_stay_duration(
    stay_duration_str: Optional[str],
    valid_from_str: Optional[str],
    valid_until_str: Optional[str],
) -> List[Violation]:
    """Check that visa stay_duration doesn't exceed visa validity window."""
    violations: List[Violation] = []
    if not stay_duration_str or not valid_from_str or not valid_until_str:
        return violations

    valid_from = parse_date(valid_from_str)
    valid_until = parse_date(valid_until_str)
    if not valid_from or not valid_until or valid_until <= valid_from:
        return violations

    window_days = (valid_until - valid_from).days

    m = re.search(r"(\d+)", stay_duration_str)
    if not m:
        return violations

    stay_days = int(m.group(1))
    if re.search(r"month", stay_duration_str, re.I):
        stay_days = stay_days * 30

    if stay_days > window_days:
        violations.append(
            Violation(
                field="stay_duration",
                rule_violated=(
                    f"Visa stay duration ({stay_days} days) exceeds visa validity window "
                    f"({window_days} days between {valid_from_str} and {valid_until_str})"
                ),
                severity=Severity.HIGH.value,
            )
        )

    return violations


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def validate_verhoeff(number_str: str) -> bool:
    digits = re.sub(r"\D", "", str(number_str or ""))
    if not digits:
        return False
    c = 0
    for i, item in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(item)]]
    return c == 0


def validate_passport_rules(fields: Dict[str, Any], mrz_dict: Optional[Dict[str, Any]] = None) -> List[Violation]:
    violations: List[Violation] = []

    # Resolve MRZ data fallback: check explicit parameter or embedded MRZ containers in fields
    mrz = mrz_dict
    if not mrz:
        for k in ("mrz_parsed", "mrz_dict", "mrz_data", "mrz", "mrz_fields"):
            v = fields.get(k)
            if v:
                mrz = v.as_dict() if hasattr(v, "as_dict") else (dict(v) if isinstance(v, dict) else None)
                if mrz:
                    break
    mrz = mrz or {}

    # 1. Passport Number: visual fields -> MRZ doc_number fallback
    pass_no = extract_field_value(fields, "passport_number", "document_number", "id_number", "doc_number")
    if not pass_no and mrz:
        pass_no = mrz.get("doc_number") or mrz.get("passport_number") or mrz.get("document_number")

    # 2. Name: visual fields -> synthesized given_names + surname -> MRZ fallback
    name = extract_field_value(fields, "name", "full_name")
    if not name:
        sur = extract_field_value(fields, "surname")
        giv = extract_field_value(fields, "given_names")
        if sur and giv:
            name = f"{giv} {sur}".strip()
        elif sur or giv:
            name = sur or giv

    if not name and mrz:
        mrz_sur = str(mrz.get("surname", "")).strip()
        mrz_giv = str(mrz.get("given_names", "")).strip()
        mrz_full = f"{mrz_giv} {mrz_sur}".strip() or mrz_sur or mrz_giv or str(mrz.get("name", "")).strip()
        if mrz_full:
            name = mrz_full

    # 3. Nationality: visual fields -> MRZ nationality fallback
    nationality = extract_field_value(fields, "nationality")
    if not nationality and mrz:
        nationality = mrz.get("nationality")

    # Any field present in the MRZ must never be reported as missing
    if not pass_no:
        violations.append(
            Violation(
                field="passport_number",
                rule_violated="Mandatory passport number is missing",
                severity=Severity.HIGH.value,
            )
        )
    else:
        clean = re.sub(r"[^A-Z0-9]", "", pass_no.upper())
        if not re.match(r"^[A-Z][0-9]{7,8}$", clean) and not (7 <= len(clean) <= 9 and clean.isalnum()):
            violations.append(
                Violation(
                    field="passport_number",
                    rule_violated=f"Invalid passport number format: {pass_no} (expected letter + 7-8 digits)",
                    severity=Severity.HIGH.value,
                )
            )
        # Country-specific format check
        if nationality:
            violations.extend(validate_passport_country_format(pass_no, nationality))

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    # MRZ checksum re-verification if MRZ lines are available
    mrz_line1 = extract_field_value(fields, "mrz_line_1", "mrz_line1", "mrzline1") or (mrz.get("raw_lines", ["", ""])[0] if (isinstance(mrz.get("raw_lines"), list) and len(mrz.get("raw_lines")) > 0) else None)
    mrz_line2 = extract_field_value(fields, "mrz_line_2", "mrz_line2", "mrzline2") or (mrz.get("raw_lines", ["", ""])[1] if (isinstance(mrz.get("raw_lines"), list) and len(mrz.get("raw_lines")) > 1) else None)
    if mrz_line1 and mrz_line2:
        violations.extend(verify_mrz_checksums(mrz_line1, mrz_line2))

    return violations


def validate_visa_rules(fields: Dict[str, Any], mrz_dict: Optional[Dict[str, Any]] = None) -> List[Violation]:
    violations: List[Violation] = []

    mrz = mrz_dict
    if not mrz:
        for k in ("mrz_parsed", "mrz_dict", "mrz_data", "mrz", "mrz_fields"):
            v = fields.get(k)
            if v:
                mrz = v.as_dict() if hasattr(v, "as_dict") else (dict(v) if isinstance(v, dict) else None)
                if mrz:
                    break
    mrz = mrz or {}

    visa_no = extract_field_value(fields, "visa_number", "document_number", "id_number", "doc_number")
    if not visa_no and mrz:
        visa_no = mrz.get("doc_number") or mrz.get("visa_number")
    valid_from = extract_field_value(fields, "valid_from", "date_of_issue", "issue_date")
    valid_until = extract_field_value(fields, "valid_until", "date_of_expiry", "expiry")
    stay_duration = extract_field_value(fields, "stay_duration", "duration_of_stay", "stay")

    if not visa_no:
        violations.append(
            Violation(
                field="visa_number",
                rule_violated="Mandatory visa number is missing",
                severity=Severity.HIGH.value,
            )
        )

    if not valid_from:
        violations.append(
            Violation(
                field="valid_from",
                rule_violated="Mandatory visa validity start date (valid_from) is missing",
                severity=Severity.HIGH.value,
            )
        )

    if not valid_until:
        violations.append(
            Violation(
                field="valid_until",
                rule_violated="Mandatory visa validity end date (valid_until) is missing",
                severity=Severity.HIGH.value,
            )
        )

    if stay_duration and valid_from and valid_until:
        stay_violations = check_visa_stay_duration(stay_duration, valid_from, valid_until)
        violations.extend(stay_violations)

    return violations


def validate_pan_rules(fields: Dict[str, Any]) -> List[Violation]:
    violations: List[Violation] = []
    pan_no = extract_field_value(fields, "pan_number", "id_number", "document_number")
    name = extract_field_value(fields, "name", "full_name", "holder_name")
    surname = extract_field_value(fields, "surname")

    if not pan_no:
        violations.append(
            Violation(
                field="pan_number",
                rule_violated="Mandatory PAN number is missing",
                severity=Severity.HIGH.value,
            )
        )
    else:
        clean = re.sub(r"[^A-Z0-9]", "", pan_no.upper())
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", clean):
            violations.append(
                Violation(
                    field="pan_number",
                    rule_violated=f"Invalid PAN format: {pan_no} (expected 5 uppercase letters + 4 digits + 1 uppercase letter)",
                    severity=Severity.CRITICAL.value,
                )
            )
        else:
            holder_char = clean[3]
            valid_holders = ("P", "C", "H", "A", "T", "F", "B", "L", "J", "G")
            if holder_char not in valid_holders:
                violations.append(
                    Violation(
                        field="pan_number",
                        rule_violated=f"Invalid PAN 4th character '{holder_char}' (must represent recognized entity type)",
                        severity=Severity.HIGH.value,
                    )
                )

            # PAN 5th-character surname match:
            # 5th character of PAN represents the first letter of the cardholder's surname
            surname_candidate = surname
            if not surname_candidate and name:
                tokens = [t for t in name.strip().split() if len(t) > 1 and t.isalpha()]
                surname_candidate = tokens[-1] if tokens else ""

            if surname_candidate:
                pan_5th = clean[4]
                surname_initial = surname_candidate[0].upper()
                first_initial = name.strip().split()[0][0].upper() if (name and name.strip()) else ""
                if pan_5th != surname_initial and pan_5th != first_initial:
                    violations.append(
                        Violation(
                            field="pan_surname_match",
                            rule_violated=(
                                f"PAN 5th-character surname match failed: PAN 5th character '{pan_5th}' "
                                f"does not match cardholder surname '{surname_candidate}' (expected '{pan_5th}', got '{surname_initial}')"
                            ),
                            severity=Severity.HIGH.value,
                        )
                    )

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory PAN holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    return violations


def validate_aadhaar_rules(fields: Dict[str, Any]) -> List[Violation]:
    violations: List[Violation] = []
    aadhaar_no = extract_field_value(fields, "aadhaar_number", "id_number", "document_number", "uid")
    name = extract_field_value(fields, "name", "full_name")

    if not aadhaar_no:
        violations.append(
            Violation(
                field="aadhaar_number",
                rule_violated="Mandatory Aadhaar number is missing",
                severity=Severity.HIGH.value,
            )
        )
    else:
        # Check for official UIDAI masked Aadhaar format (e.g. 'XXXX XXXX 1107')
        masked, last4 = is_masked_aadhaar(aadhaar_no)
        if masked:
            # Masked Aadhaar is a valid document, not a missing field.
            # Full number is not printed; Verhoeff checksum is skipped and zero violations/risk points are added.
            pass
        else:
            clean = re.sub(r"\D", "", aadhaar_no)
            if len(clean) != 12:
                violations.append(
                    Violation(
                        field="aadhaar_number",
                        rule_violated=f"Aadhaar number must be exactly 12 digits, got {len(clean)}",
                        severity=Severity.HIGH.value,
                    )
                )
            elif clean[0] in ("0", "1"):
                violations.append(
                    Violation(
                        field="aadhaar_number",
                        rule_violated=f"Aadhaar first digit cannot be 0 or 1 (starts with '{clean[0]}')",
                        severity=Severity.HIGH.value,
                    )
                )
            elif not validate_verhoeff(clean):
                violations.append(
                    Violation(
                        field="aadhaar_checksum",
                        rule_violated=f"Aadhaar Verhoeff checksum validation failed for {aadhaar_no}",
                        severity=Severity.CRITICAL.value,
                    )
                )

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory Aadhaar holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    return violations


def validate_voter_rules(fields: Dict[str, Any]) -> List[Violation]:
    violations: List[Violation] = []
    epic_no = extract_field_value(fields, "voter_id_number", "epic_number", "id_number", "document_number")
    name = extract_field_value(fields, "name", "full_name")

    if not epic_no:
        violations.append(
            Violation(
                field="voter_id_number",
                rule_violated="Mandatory Voter ID (EPIC) number is missing",
                severity=Severity.HIGH.value,
            )
        )
    else:
        clean = re.sub(r"[^A-Z0-9]", "", epic_no.upper())
        if not re.match(r"^[A-Z]{3}[0-9]{7}$", clean) and len(clean) < 8:
            violations.append(
                Violation(
                    field="voter_id_number",
                    rule_violated=f"Invalid Voter ID format: {epic_no} (expected standard 3 letters + 7 digits)",
                    severity=Severity.HIGH.value,
                )
            )

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory Voter ID holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    return violations


def validate_dl_rules(fields: Dict[str, Any]) -> List[Violation]:
    violations: List[Violation] = []
    dl_no = extract_field_value(fields, "driving_licence_number", "license_number", "dl_number", "id_number")
    name = extract_field_value(fields, "name", "full_name")

    if not dl_no:
        violations.append(
            Violation(
                field="driving_licence_number",
                rule_violated="Mandatory Driving Licence number is missing",
                severity=Severity.HIGH.value,
            )
        )
    else:
        clean = re.sub(r"[^A-Z0-9]", "", dl_no.upper())
        if len(clean) < 10 or not re.match(r"^[A-Z]{2}", clean):
            violations.append(
                Violation(
                    field="driving_licence_number",
                    rule_violated=f"Invalid Driving Licence format: {dl_no} (must start with 2-letter state code and be at least 10 characters)",
                    severity=Severity.HIGH.value,
                )
            )

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory Driving Licence holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    return violations


def validate_permit_rules(fields: Dict[str, Any]) -> List[Violation]:
    violations: List[Violation] = []
    permit_no = extract_field_value(fields, "permit_number", "id_number", "document_number")
    name = extract_field_value(fields, "name", "full_name")

    if not permit_no:
        violations.append(
            Violation(
                field="permit_number",
                rule_violated="Mandatory permit number is missing",
                severity=Severity.HIGH.value,
            )
        )

    if not name:
        violations.append(
            Violation(
                field="name",
                rule_violated="Mandatory permit holder name is missing",
                severity=Severity.HIGH.value,
            )
        )

    return violations
