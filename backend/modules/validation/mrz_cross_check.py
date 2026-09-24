"""
mrz_cross_check.py - Cross-check between MRZ fields and printed visual inspection zone (VIZ).

Implements:
1. Extraction of printed visual fields via label_anchor.
2. Extraction and check-digit validation of MRZ fields via mrz_reader & mrz_checks.
3. Positional cross-verification:
   - Exact mismatch on NUMERIC or CODE field (document number, dates, nationality, sex) -> TAMPERING.
   - Explainable OCR-B confusion on NAME fields (W<->M, W<->NN, M<->N, O<->0, I<->1, S<->5, B<->8, rn<->m)
     -> OCR ARTIFACT (reported as low confidence, does NOT flag tampering).
   - Unexplainable name difference (different length, different starting letters, distinct name) -> TAMPERING.
   - Either side unreadable or missing -> SKIPPED with an explicit reason naming the field.
4. Expiry evaluation against current reference date -> EXPIRED.
5. Pristine match -> VERIFIED.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
from backend.modules.ocr_extraction.label_anchor import (
    boxes_from_raw_results,
    extract_fields_cascade,
)
from backend.modules.ocr_extraction.mrz_reader import read_mrz, ISO_3166_1_CODES
from backend.modules.validation.mrz_checks import (
    validate_and_correct_mrz,
    CONF_THRESHOLD,
)

# Demonyms and country names mapped to ISO 3166-1 alpha-3 codes
# (Reusing and extending nationality_to_code from rules_engine.py line 189)
NATIONALITY_TO_ALPHA3: Dict[str, str] = {
    # rules_engine.py line 189 mapping to alpha-3:
    "INDIAN": "IND", "INDIA": "IND", "IND": "IND", "IN": "IND",
    "AMERICAN": "USA", "USA": "USA", "UNITED STATES": "USA", "UNITED STATES OF AMERICA": "USA", "US": "USA",
    "BRITISH": "GBR", "GBR": "GBR", "UNITED KINGDOM": "GBR", "GREAT BRITAIN": "GBR", "UK": "GBR", "GB": "GBR",
    "CANADIAN": "CAN", "CANADA": "CAN", "CAN": "CAN", "CA": "CAN",
    "AUSTRALIAN": "AUS", "AUSTRALIA": "AUS", "AUS": "AUS", "AU": "AUS",
    "FRENCH": "FRA", "FRANCE": "FRA", "FRA": "FRA", "FR": "FRA",
    "GERMAN": "DEU", "GERMANY": "DEU", "DEUTSCHLAND": "DEU", "DEU": "DEU", "DE": "DEU",
    "EMIRATI": "ARE", "UAE": "ARE", "ARE": "ARE", "UNITED ARAB EMIRATES": "ARE", "AE": "ARE",
    "SINGAPOREAN": "SGP", "SINGAPORE": "SGP", "SGP": "SGP", "SG": "SGP",
    "CHINESE": "CHN", "CHINA": "CHN", "CHN": "CHN", "CN": "CHN",
    "NIGERIAN": "NGA", "NIGERIA": "NGA", "NGA": "NGA", "NG": "NGA",
    # Extended common nationalities / demonyms:
    "PAKISTANI": "PAK", "PAKISTAN": "PAK", "PAK": "PAK", "PK": "PAK",
    "BANGLADESHI": "BGD", "BANGLADESH": "BGD", "BGD": "BGD", "BD": "BGD",
    "NEPALESE": "NPL", "NEPALI": "NPL", "NEPAL": "NPL", "NPL": "NPL", "NP": "NPL",
    "SRI LANKAN": "LKA", "SRI LANKA": "LKA", "LKA": "LKA", "LK": "LKA",
    "JAPANESE": "JPN", "JAPAN": "JPN", "JPN": "JPN", "JP": "JPN",
    "MEXICAN": "MEX", "MEXICO": "MEX", "MEX": "MEX", "MX": "MEX",
    "BRAZILIAN": "BRA", "BRAZIL": "BRA", "BRASIL": "BRA", "BRA": "BRA", "BR": "BRA",
    "RUSSIAN": "RUS", "RUSSIA": "RUS", "RUS": "RUS", "RU": "RUS",
    "ITALIAN": "ITA", "ITALY": "ITA", "ITALIA": "ITA", "ITA": "ITA", "IT": "ITA",
    "SPANISH": "ESP", "SPAIN": "ESP", "ESPANA": "ESP", "ESP": "ESP", "ES": "ESP",
    "DUTCH": "NLD", "NETHERLANDS": "NLD", "HOLLAND": "NLD", "NLD": "NLD", "NL": "NLD",
    "UTOPIA": "UTO", "UTOPIAN": "UTO", "UTO": "UTO",
}


def normalize_nationality_to_code(nat: Optional[str]) -> str:
    """
    Normalizes demonyms, country names, or alpha-2/alpha-3 country codes
    to standard ISO 3166-1 alpha-3 code.
    """
    if not nat:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(nat)).upper().strip()
    if not cleaned:
        return ""
    if cleaned in NATIONALITY_TO_ALPHA3:
        return NATIONALITY_TO_ALPHA3[cleaned]
    spaced = " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", str(nat)).upper().split())
    if spaced in NATIONALITY_TO_ALPHA3:
        return NATIONALITY_TO_ALPHA3[spaced]
    if len(cleaned) == 3:
        return cleaned
    return cleaned


# Known OCR-B visual confusion pairs
OCR_B_CONFUSIONS: List[Tuple[str, str]] = [
    ("W", "M"), ("M", "W"),
    ("W", "NN"), ("NN", "W"),
    ("M", "N"), ("N", "M"),
    ("W", "N"), ("N", "W"),
    ("O", "0"), ("0", "O"),
    ("I", "1"), ("1", "I"),
    ("S", "5"), ("5", "S"),
    ("B", "8"), ("8", "B"),
    ("RN", "M"), ("M", "RN"),
]


def explainable_by_ocr_b(s1: str, s2: str) -> Tuple[bool, List[str]]:
    """
    Checks if s1 can be transformed into s2 using ONLY allowed OCR-B substitutions.
    Returns (is_explainable, list_of_artifacts_found).
    """
    s1_clean = s1.upper().replace(" ", "")
    s2_clean = s2.upper().replace(" ", "")
    if s1_clean == s2_clean:
        return True, []

    memo: Dict[Tuple[int, int], Tuple[bool, List[str]]] = {}

    def dp(i: int, j: int) -> Tuple[bool, List[str]]:
        if (i, j) in memo:
            return memo[(i, j)]

        if i == len(s1_clean) and j == len(s2_clean):
            return True, []
        if i == len(s1_clean) or j == len(s2_clean):
            return False, []

        # Direct character match
        if s1_clean[i] == s2_clean[j]:
            ok, arts = dp(i + 1, j + 1)
            if ok:
                memo[(i, j)] = (True, arts)
                return True, arts

        # Allowed confusion match
        for c1, c2 in OCR_B_CONFUSIONS:
            l1, l2 = len(c1), len(c2)
            if s1_clean[i:i + l1] == c1 and s2_clean[j:j + l2] == c2:
                ok, arts = dp(i + l1, j + l2)
                if ok:
                    res_arts = [f"{c1}<->{c2}"] + arts
                    memo[(i, j)] = (True, res_arts)
                    return True, res_arts

        memo[(i, j)] = (False, [])
        return False, []

    return dp(0, 0)


def parse_mrz_line1_names(line1: str) -> Tuple[str, str]:
    """
    Extracts surname and given names from ICAO 9303 Line 1.
    Format: P<UTO[SURNAME]<<[GIVEN_NAMES]... or V<UTO[SURNAME]<<[GIVEN_NAMES]...
    """
    clean_line = line1.strip().upper()
    if len(clean_line) >= 5:
        name_part = clean_line[5:].rstrip("<")
        parts = name_part.split("<<", 1)
        sur = parts[0].replace("<", " ").strip()
        giv = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""
        return sur, giv
    return "", ""


def _normalize_date_to_yymmdd(d_str: str) -> Optional[str]:
    """Normalizes DD/MM/YYYY or YYYY-MM-DD or YYMMDD string to YYMMDD."""
    if not d_str:
        return None
    s = d_str.strip().replace("-", "/").replace(".", "/")
    parts = s.split("/")
    if len(parts) == 3:
        # DD/MM/YYYY
        if len(parts[2]) == 4 and parts[2].isdigit() and parts[1].isdigit() and parts[0].isdigit():
            return parts[2][-2:] + parts[1].zfill(2) + parts[0].zfill(2)
        # YYYY/MM/DD
        elif len(parts[0]) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return parts[0][-2:] + parts[1].zfill(2) + parts[2].zfill(2)
    # Regex search for DD/MM/YYYY
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return yyyy[-2:] + mm.zfill(2) + dd.zfill(2)
    # OCR artifact where slash was read as 2 (e.g. 20/0422025 -> 20/04/2025)
    m2 = re.search(r"\b(\d{2})[/.-](\d{2})[2/](\d{4})\b", s)
    if m2:
        dd, mm, yyyy = m2.group(1), m2.group(2), m2.group(3)
        return yyyy[-2:] + mm.zfill(2) + dd.zfill(2)
    clean_digits = re.sub(r"\D", "", s)
    if len(clean_digits) == 6 and clean_digits.isdigit():
        return clean_digits
    if len(clean_digits) == 8 and clean_digits.isdigit():
        if int(clean_digits[4:8]) >= 1950 and 1 <= int(clean_digits[2:4]) <= 12:
            return clean_digits[6:8] + clean_digits[2:4] + clean_digits[0:2]
        elif int(clean_digits[0:4]) >= 1950 and 1 <= int(clean_digits[4:6]) <= 12:
            return clean_digits[2:4] + clean_digits[4:6] + clean_digits[6:8]
    return None


def cross_check_mrz_vs_printed(
    image: np.ndarray,
    document_type: str = "passport",
    doc_id: str = "",
    reference_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Main cross-check orchestrator between MRZ and printed visual inspection zone (VIZ).
    """
    if reference_date is None:
        reference_date = datetime.now().date()

    doc_type_norm = "passport" if "passport" in document_type.lower() else "visa"
    h, w = image.shape[:2]

    # 1. Extract printed fields via label_anchor
    reader = _easyocr_engine.get_reader("en")
    raw_res = reader.readtext(image)
    boxes = boxes_from_raw_results(raw_res, img_shape=(h, w))
    full_text = "\n".join(b.text for b in boxes)
    printed_raw, _ = extract_fields_cascade(boxes, doc_type_norm, full_text=full_text, image=image)
    printed_fields = {k: v[0] for k, v in printed_raw.items()}

    # Supplement missing printed visual fields for visa if label_anchor missed them
    if doc_type_norm == "visa":
        if "date_of_expiry" not in printed_fields:
            for b in boxes:
                if 0.58 <= b.ymin <= 0.75 and 0.05 <= b.xmin <= 0.35:
                    d_clean = _normalize_date_to_yymmdd(b.text)
                    if d_clean:
                        printed_fields["date_of_expiry"] = b.text.strip()
                        break
        if "surname" not in printed_fields or "given_names" not in printed_fields:
            for b in boxes:
                if 0.22 <= b.ymin <= 0.35 and 0.05 <= b.xmin <= 0.35:
                    t = b.text.strip()
                    if len(t) > 3 and not any(k in t.upper() for k in ("NAME", "NOM", "PASSPORT", "VISA")):
                        parts = re.split(r"[,;]", t, 1)
                        if len(parts) == 2:
                            printed_fields["surname"] = parts[0].strip()
                            printed_fields["given_names"] = parts[1].strip()
                        else:
                            sub_parts = t.split()
                            if len(sub_parts) >= 2:
                                printed_fields["surname"] = sub_parts[0].strip()
                                printed_fields["given_names"] = " ".join(sub_parts[1:]).strip()
                        break

    # 2. Extract and validate MRZ
    mrz_res = read_mrz(image, doc_type=doc_type_norm, doc_id=doc_id)
    val_res = validate_and_correct_mrz(
        mrz_res["raw_lines"],
        mrz_res["clean_lines"],
        doc_type=doc_type_norm,
        confidences_l2=mrz_res.get("char_confidences_l2"),
    )
    mrz_fields = val_res["fields"]
    mrz_sur, mrz_giv = parse_mrz_line1_names(val_res["final_lines"][0])
    mrz_fields["surname"] = mrz_sur
    mrz_fields["given_names"] = mrz_giv

    ocr_artifacts: List[Dict[str, Any]] = []

    # 3. Check MRZ Check Digits
    if not val_res["all_valid_after"]:
        failing = [k for k, v in val_res["valid_after"].items() if v is False]
        field_name = failing[0] if failing else "mrz_checksum"
        return {
            "outcome": "TAMPERED",
            "field": field_name,
            "reason": f"MRZ checksum verification failed on field '{field_name}'",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": False,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }

    # 4. Cross-Check Document / Visa Number
    p_num = printed_fields.get("passport_number" if doc_type_norm == "passport" else "visa_number")
    m_num = mrz_fields.get("document_number")
    if not p_num or not m_num:
        return {
            "outcome": "SKIPPED",
            "field": "document_number",
            "reason": "Document number unreadable on printed visual zone or MRZ",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }
    if p_num.strip().upper() != m_num.strip().upper():
        return {
            "outcome": "TAMPERED",
            "field": "document_number",
            "reason": f"Document number mismatch: printed '{p_num}' conflicts with MRZ '{m_num}'",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }

    # 5. Cross-Check Date of Birth (Passport or when printed)
    if doc_type_norm == "passport" or ("date_of_birth" in printed_fields):
        p_dob = printed_fields.get("date_of_birth")
        m_dob = mrz_fields.get("date_of_birth")
        if not p_dob or not m_dob:
            return {
                "outcome": "SKIPPED",
                "field": "date_of_birth",
                "reason": "Date of birth unreadable on printed visual zone or MRZ",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }
        p_dob_yymmdd = _normalize_date_to_yymmdd(p_dob)
        if not p_dob_yymmdd:
            return {
                "outcome": "SKIPPED",
                "field": "date_of_birth",
                "reason": f"Printed date of birth '{p_dob}' could not be parsed to standard date format",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }
        if p_dob_yymmdd != m_dob:
            return {
                "outcome": "TAMPERED",
                "field": "date_of_birth",
                "reason": f"Date of birth mismatch: printed '{p_dob}' ({p_dob_yymmdd}) conflicts with MRZ '{m_dob}'",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }

    # 6. Cross-Check Date of Expiry
    p_exp = printed_fields.get("date_of_expiry")
    m_exp = mrz_fields.get("date_of_expiry")
    if not p_exp or not m_exp:
        return {
            "outcome": "SKIPPED",
            "field": "date_of_expiry",
            "reason": "Date of expiry unreadable on printed visual zone or MRZ",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }
    p_exp_yymmdd = _normalize_date_to_yymmdd(p_exp)
    if not p_exp_yymmdd:
        return {
            "outcome": "SKIPPED",
            "field": "date_of_expiry",
            "reason": f"Printed date of expiry '{p_exp}' could not be parsed to standard date format",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }
    if p_exp_yymmdd != m_exp:
        return {
            "outcome": "TAMPERED",
            "field": "date_of_expiry",
            "reason": f"Expiry date mismatch: printed '{p_exp}' ({p_exp_yymmdd}) conflicts with MRZ '{m_exp}'",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }

    # 7. Cross-Check Nationality (Passport or when printed)
    if doc_type_norm == "passport" or ("nationality" in printed_fields):
        p_nat = printed_fields.get("nationality")
        m_nat = mrz_fields.get("nationality")
        if not p_nat or not m_nat:
            return {
                "outcome": "SKIPPED",
                "field": "nationality",
                "reason": "Nationality unreadable on printed visual zone or MRZ",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }
        p_code = normalize_nationality_to_code(p_nat)
        m_code = normalize_nationality_to_code(m_nat)

        # Compare codes to codes; a word-vs-code difference for the same country must never be flagged as tampering
        if p_code == m_code or p_nat.strip().upper() == m_nat.strip().upper():
            pass
        elif len(m_code) == 3 and m_code in p_nat.strip().upper():
            pass
        elif len(p_code) == 3 and p_code in m_nat.strip().upper():
            pass
        else:
            p_is_word = len(p_nat.strip()) > 3
            m_is_code = len(m_nat.strip()) <= 3
            # If word vs code and not confirmed conflicting ISO codes, never flag tampering
            if (p_is_word and m_is_code) or (p_code not in ISO_3166_1_CODES or m_code not in ISO_3166_1_CODES):
                return {
                    "outcome": "SKIPPED",
                    "field": "nationality",
                    "reason": f"Nationality word-vs-code difference: printed '{p_nat}' vs MRZ '{m_nat}'",
                    "printed_fields": printed_fields,
                    "mrz_fields": mrz_fields,
                    "check_digits_valid": True,
                    "check_digit_details": val_res["valid_after"],
                    "ocr_artifacts": [],
                }
            return {
                "outcome": "TAMPERED",
                "field": "nationality",
                "reason": f"Nationality mismatch: printed '{p_nat}' conflicts with MRZ '{m_nat}'",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }

    # 8. Cross-Check Sex / Gender (Passport or when printed)
    if doc_type_norm == "passport" or ("sex" in printed_fields):
        p_sex = printed_fields.get("sex", "").strip().upper()
        m_sex = mrz_fields.get("sex", "").strip().upper()
        if not p_sex or not m_sex or m_sex == "<":
            return {
                "outcome": "SKIPPED",
                "field": "sex",
                "reason": f"Sex field unreadable or unspecified in MRZ ('{m_sex}')",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }
        if p_sex[:1] != m_sex[:1]:
            return {
                "outcome": "TAMPERED",
                "field": "sex",
                "reason": f"Sex code mismatch: printed '{p_sex}' conflicts with MRZ '{m_sex}'",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }

    # 9. Cross-Check Names (Surname & Given Names)
    p_sur = printed_fields.get("surname", "").strip().upper()
    p_giv = printed_fields.get("given_names", "").strip().upper()
    if not p_sur or not mrz_sur:
        return {
            "outcome": "SKIPPED",
            "field": "surname",
            "reason": "Surname unreadable on printed visual zone or MRZ",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }

    # Surname OCR-B verification
    sur_ok, sur_arts = explainable_by_ocr_b(p_sur, mrz_sur)
    if not sur_ok:
        return {
            "outcome": "TAMPERED",
            "field": "surname",
            "reason": f"Surname mismatch not explainable by OCR confusion: printed '{p_sur}' vs MRZ '{mrz_sur}'",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": [],
        }
    if sur_arts:
        ocr_artifacts.append({"field": "surname", "printed": p_sur, "mrz": mrz_sur, "confusions": sur_arts})

    # Given Names OCR-B verification (if present on both)
    if p_giv and mrz_giv:
        giv_ok, giv_arts = explainable_by_ocr_b(p_giv, mrz_giv)
        if not giv_ok:
            return {
                "outcome": "TAMPERED",
                "field": "given_names",
                "reason": f"Given names mismatch not explainable by OCR confusion: printed '{p_giv}' vs MRZ '{mrz_giv}'",
                "printed_fields": printed_fields,
                "mrz_fields": mrz_fields,
                "check_digits_valid": True,
                "check_digit_details": val_res["valid_after"],
                "ocr_artifacts": [],
            }
        if giv_arts:
            ocr_artifacts.append({"field": "given_names", "printed": p_giv, "mrz": mrz_giv, "confusions": giv_arts})

    # 10. Expiry Date Check
    exp_yy = int(p_exp_yymmdd[:2])
    exp_century = 2000 if exp_yy < 70 else 1900
    exp_year = exp_century + exp_yy
    exp_month = int(p_exp_yymmdd[2:4])
    exp_day = int(p_exp_yymmdd[4:6])
    doc_exp_date = date(exp_year, exp_month, exp_day)

    if doc_exp_date < reference_date:
        return {
            "outcome": "EXPIRED",
            "field": "date_of_expiry",
            "reason": f"Document expired on {doc_exp_date} (prior to reference date {reference_date})",
            "printed_fields": printed_fields,
            "mrz_fields": mrz_fields,
            "check_digits_valid": True,
            "check_digit_details": val_res["valid_after"],
            "ocr_artifacts": ocr_artifacts,
        }

    return {
        "outcome": "VERIFIED",
        "field": None,
        "reason": "Document integrity verified; all printed visual fields match verified MRZ",
        "printed_fields": printed_fields,
        "mrz_fields": mrz_fields,
        "check_digits_valid": True,
        "check_digit_details": val_res["valid_after"],
        "ocr_artifacts": ocr_artifacts,
    }
