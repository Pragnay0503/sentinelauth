"""
field_extractor.py - Per-document-type field extraction.

Primary engine: PaddleOCR via ocr_engine.py.
Fallback engine: pytesseract (triggered if PaddleOCR avg confidence < 0.5 or on error).
Supports: Passport, Visa, PAN Card, Aadhaar Card, Voter ID, Driving License, Permit.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .ocr_engine import extract_raw_text, RawResult
from .checksums import (
    validate_pan_format,
    validate_verhoeff,
    validate_epic_format,
    decode_pan_details,
)


# ---------------------------------------------------------------------------
# Date normalisation helpers
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    re.compile(r"\b(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b"),   # DD/MM/YYYY
    re.compile(r"\b(\d{4})[/\-.](\d{2})[/\-.](\d{2})\b"),   # YYYY-MM-DD
    re.compile(r"\b(\d{2})\s+(\w{3})\s+(\d{4})\b"),         # 12 JAN 2025
]


def _extract_date(text: str) -> Optional[str]:
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Generic label-value extractor
# ---------------------------------------------------------------------------

_FIELD_BOUNDARY_KEYWORDS = (
    r"SURNAME|LAST NAME|GIVEN NAME|GIVEN NAMES|FIRST NAME|FULL NAME|HOLDER|"
    r"FATHER'?S? NAME|HUSBAND'?S? NAME|RELATION'?S? NAME|"
    r"PASSPORT NO|PASSPORT NUMBER|DOCUMENT NO|VISA NO|VISA NUMBER|ID NO|ID NUMBER|"
    r"LICEN[CS]E NO|DL NO|PERMIT NO|AADHAAR NO|PAN NO|PAN NUMBER|EPIC NO|EPIC NUMBER|"
    r"NATIONALITY|NATION|DATE OF BIRTH|DOB|YEAR OF BIRTH|YOB|BIRTH DATE|DATE OF EXPIRY|EXPIRY DATE|"
    r"VALID UNTIL|VALID TILL|EXPIRY|EXPIRATION|SEX|GENDER|PLACE OF ISSUE|ISSUED AT|"
    r"ISSUED BY|ISSUING COUNTRY|DURATION OF STAY|STAY|VALID FROM|ENTRY FROM|"
    r"VISA TYPE|VISA CATEGORY|MACHINE READABLE|PHOTO|ADDRESS|COV|INCOME TAX|ELECTION COMMISSION"
)


def _extract_after_label(text: str, labels: List[str], max_chars: int = 60) -> Optional[str]:
    """
    Find the first label in text (case-insensitive) and return the text following it on the same line or next segment.
    """
    for label in labels:
        pat = re.compile(
            rf"\b{re.escape(label)}\b\s*[:/\-]?\s*(.+)",
            re.IGNORECASE
        )
        m = pat.search(text)
        if m:
            rest = m.group(1).strip()
            first_line = rest.splitlines()[0] if rest.splitlines() else rest
            value = re.split(rf"\b(?:{_FIELD_BOUNDARY_KEYWORDS})\b\s*[:\-]?", first_line, flags=re.IGNORECASE)[0]
            value = value.strip(" :,-/|\t\r\n")
            if value:
                return value[:max_chars].strip()
    return None


def _best_confidence(raw: RawResult, value: str) -> float:
    """Find the highest confidence score for tokens matching a value."""
    if not value or not raw:
        return 0.85
    val_lower = value.lower()
    val_tokens = set(val_lower.split())
    scores = []
    for text, conf in raw:
        t_low = text.lower()
        if t_low in val_tokens or any(tok in t_low for tok in val_tokens) or t_low in val_lower:
            scores.append(conf)
    return round(max(scores), 3) if scores else 0.85


# ---------------------------------------------------------------------------
# Document Subtype Auto-Detection
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Document Subtype Auto-Detection & Carried Fields Specification
# ---------------------------------------------------------------------------

CARRIED_FIELDS_BY_DOC_TYPE: Dict[str, set] = {
    "passport": {
        "passport_number", "document_number", "name", "full_name", "surname",
        "given_names", "nationality", "date_of_birth", "dob", "gender", "sex",
        "date_of_issue", "date_of_expiry", "expiry_date", "valid_until",
        "place_of_birth", "place_of_issue", "mrz_line_1", "mrz_line_2",
    },
    "national_id_aadhaar": {
        "aadhaar_number", "document_number", "name", "full_name", "date_of_birth",
        "dob", "year_of_birth", "yob", "gender", "sex", "address",
        "father_name", "husband_name", "guardian_name", "qr_code",
    },
    "national_id_pan": {
        "pan_number", "document_number", "name", "full_name", "holder_name",
        "surname", "father_name", "date_of_birth", "dob",
    },
    "driving_license": {
        "driving_licence_number", "dl_number", "document_number", "name", "full_name",
        "date_of_birth", "dob", "date_of_issue", "date_of_expiry", "valid_until",
        "blood_group", "vehicle_classes", "address",
    },
    "visa": {
        "visa_number", "document_number", "name", "full_name", "surname", "given_names",
        "passport_number", "nationality", "date_of_birth", "dob", "gender", "sex",
        "valid_from", "valid_until", "date_of_expiry", "expiry_date",
        "stay_duration", "visa_type", "entries", "mrz_line_1", "mrz_line_2",
    },
    "national_id_voter": {
        "epic_number", "voter_id_number", "document_number", "name", "full_name",
        "relation_name", "date_of_birth", "dob", "gender", "sex", "address",
    },
}

DOC_TYPE_DISPLAY_NAMES: Dict[str, str] = {
    "passport": "Passport",
    "national_id_aadhaar": "Aadhaar",
    "aadhaar": "Aadhaar",
    "national_id_pan": "PAN",
    "pan": "PAN",
    "driving_license": "Driving Licence",
    "dl": "Driving Licence",
    "visa": "Visa",
    "national_id_voter": "Voter ID",
    "permit": "Permit",
    "auto": "Auto-Detect",
}


def detect_document_subtype(raw_ocr_text: str, img: Optional[np.ndarray] = None) -> Optional[str]:
    """
    Auto-classifies every upload directly from the image and extracted text:
      - Passport: MRZ present, ICAO TD3 layout (2 lines x 44 chars, P< prefix), passport headers
      - Aadhaar: 12-digit number, UIDAI QR, Hindi+English bilingual layout, UIDAI anchors
      - PAN: 10-char alphanumeric AAAAA9999A, Income Tax Dept header
      - Driving Licence: state RTO format (2-letter state code + RTO numbers + year + serial)
      - Visa: Entry visa headers, V< MRZ
      - Voter ID: Election Commission, EPIC format
    """
    upper = raw_ocr_text.upper()

    # ------------------------------------------------------------------
    # 1. Visa (Checked before Passport because Visas state 'Passport No')
    # ------------------------------------------------------------------
    if (
        "ENTRY VISA" in upper
        or "VISA NO" in upper
        or "VISA NUMBER" in upper
        or "VISA TYPE" in upper
        or "DURATION OF STAY" in upper
        or "IMMIGRATION VISA" in upper
        or "IMMIGRATION ENTRY PERMIT" in upper
        or re.search(r"\bV[<A-Z0-9]{10,}", upper)
        or ("VISA" in upper and ("ENTRIES" in upper or "SINGLE" in upper or "MULTIPLE" in upper))
    ):
        return "visa"

    # ------------------------------------------------------------------
    # 2. Passport: MRZ present, ICAO TD3 layout, Passport headers
    # ------------------------------------------------------------------
    has_td3_mrz = bool(
        re.search(r"\bP<[A-Z]{3}", upper)
        or re.search(r"P[<A-Z0-9]{35,}", upper)
        or (upper.count("<") >= 10 and re.search(r"P[<A-Z]", upper))
    )
    if (
        has_td3_mrz
        or "REPUBLIC OF INDIA PASSPORT" in upper
        or "PASSPORT" in upper
        or "PASSEPORT" in upper
        or "TRAVEL DOCUMENT" in upper
        or "MINISTRY OF EXTERNAL AFFAIRS" in upper
        or "TYPE/TYPE P" in upper
        or "TYPE P" in upper
        or re.search(r"\bP[<A-Z0-9]{10,}", upper)
    ):
        return "passport"

    # ------------------------------------------------------------------
    # 3. PAN Card: 10-char alphanumeric AAAAA9999A, Income Tax Dept header
    # ------------------------------------------------------------------
    has_pan_regex = bool(re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", upper))
    has_pan_header = bool(
        "INCOME TAX" in upper
        or "PERMANENT ACCOUNT" in upper
        or ("GOVT" in upper and "INDIA" in upper and ("ACCOUNT" in upper or "TAX" in upper or "PAN" in upper))
        or "PAN CARD" in upper
    )
    if (has_pan_regex and has_pan_header) or (has_pan_regex and ("FATHER" in upper or "DATE OF BIRTH" in upper or "SIGNATURE" in upper)) or ("INCOME TAX DEPARTMENT" in upper and "PERMANENT ACCOUNT NUMBER" in upper):
        return "national_id_pan"

    # ------------------------------------------------------------------
    # 4. Voter ID / EPIC (Checked before generic Aadhaar rules)
    # ------------------------------------------------------------------
    if (
        "ELECTION COMMISSION" in upper
        or "ELECTOR PHOTO IDENTITY" in upper
        or "ELECTOR" in upper
        or "EPIC NO" in upper
        or "EPIC NUMBER" in upper
        or "BHARAT NIRVACHAN" in upper
        or re.search(r"\b[A-Z]{3}[0-9]{7}\b", upper)
    ):
        return "national_id_voter"

    # ------------------------------------------------------------------
    # 5. Aadhaar: 12-digit number, UIDAI QR, Hindi+English bilingual layout
    # ------------------------------------------------------------------
    has_aadhaar_12digit = bool(
        re.search(r"\b\d{4}\s+\d{4}\s+\d{4}\b", upper)
        or re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", upper)
    )
    has_hindi_bilingual = bool(
        re.search(r"[\u0900-\u097F]", raw_ocr_text)
        or "BHARAT SARKAR" in upper
        or "MERA AADHAAR" in upper
        or "AAM AADMI" in upper
        or "PEHCHAN" in upper
    )
    has_uidai_qr_or_anchor = bool(
        "UNIQUE IDENTIFICATION" in upper
        or "AADHAAR" in upper
        or "UIDAI" in upper
        or "ENROLMENT NO" in upper
        or re.search(r"\bVID\s*:\s*\d{4}\b", upper)
    )
    if img is not None and not has_uidai_qr_or_anchor:
        try:
            from .preprocessing import detect_qr_code_presence
            if detect_qr_code_presence(img):
                has_uidai_qr_or_anchor = True
        except Exception:
            pass

    if (
        (has_aadhaar_12digit and (has_uidai_qr_or_anchor or has_hindi_bilingual))
        or (has_uidai_qr_or_anchor and has_hindi_bilingual)
        or ("AADHAAR" in upper and (has_aadhaar_12digit or "GOVERNMENT OF INDIA" in upper or "DOB" in upper))
        or ("UNIQUE IDENTIFICATION" in upper)
        or ("MERA AADHAAR" in upper)
        or (has_aadhaar_12digit and ("GOVERNMENT OF INDIA" in upper or "GOVT OF INDIA" in upper or "MALE" in upper or "FEMALE" in upper))
    ):
        return "national_id_aadhaar"

    # ------------------------------------------------------------------
    # 6. Driving Licence: State RTO format, DL keywords
    # ------------------------------------------------------------------
    has_rto_format = bool(
        re.search(r"\b[A-Z]{2}[- /]?[0-9]{2,4}[- /]?[0-9]{4}[- /]?[0-9]{4,8}\b", upper)
        or re.search(r"\bDL[- /]?[0-9]{11,15}\b", upper)
        or re.search(r"\b[A-Z]{2}\d{13,15}\b", upper)
    )
    if (
        "DRIVING LICENCE" in upper
        or "DRIVING LICENSE" in upper
        or "UNION OF INDIA DRIVING" in upper
        or "LICENCE TO DRIVE" in upper
        or "FORM 7" in upper
        or "DL NO" in upper
        or "DLNO" in upper
        or "TRANSPORT DEPARTMENT" in upper
        or "SARATHI" in upper
        or "MOTOR VEHICLES" in upper
        or "AUTHORITY TO DRIVE" in upper
        or (has_rto_format and ("AUTHORITY" in upper or "VEHICLE" in upper or "COV" in upper or "VALID" in upper))
    ):
        return "driving_license"

    # Fallback checks: PAN standalone format if not previously returned
    if has_pan_regex:
        return "national_id_pan"

    # Fallback checks: Aadhaar standalone 12-digit number
    if has_aadhaar_12digit:
        return "national_id_aadhaar"

    # Fallback checks: RTO format alone
    if has_rto_format:
        return "driving_license"

    return None


# ---------------------------------------------------------------------------
# PAN Card Extractor
# ---------------------------------------------------------------------------

def _extract_pan_fields(text: str, raw: RawResult) -> Tuple[Dict[str, Tuple[str, float]], bool]:
    """
    Extracts structured fields from PAN Card:
    - PAN Number (5 letters + 4 digits + 1 letter)
    - Name
    - Father's Name
    - Date of Birth
    - Issuing Authority (anchor phrase)
    Returns (fields, anchor_phrase_found)
    """
    fields: Dict[str, Tuple[str, float]] = {}
    upper = text.upper()

    # Anchor check: "INCOME TAX DEPARTMENT" or "GOVT OF INDIA"
    anchor_found = ("INCOME TAX DEPARTMENT" in upper) or ("GOVT OF INDIA" in upper) or ("GOVERNMENT OF INDIA" in upper)

    if anchor_found:
        fields["issuing_authority"] = ("INCOME TAX DEPARTMENT, GOVT OF INDIA", 0.95)

    # PAN Number
    pan_match = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", upper)
    if pan_match:
        pan_no = pan_match.group(0)
        fields["pan_number"] = (pan_no, _best_confidence(raw, pan_no))
    else:
        p_val = _extract_after_label(text, ["PAN NO", "PAN NUMBER", "PERMANENT ACCOUNT NUMBER"])
        if p_val:
            fields["pan_number"] = (p_val, _best_confidence(raw, p_val))

    # Decode PAN holder type and surname initial
    pan_val_extracted = fields.get("pan_number", (None, 0.0))[0]
    if pan_val_extracted:
        details = decode_pan_details(pan_val_extracted)
        if details.get("pan_holder_type"):
            fields["pan_holder_type"] = (details["pan_holder_type"], 0.95)
        if details.get("surname_initial"):
            fields["surname_initial"] = (details["surname_initial"], 0.95)

    # Name (excluding Father's Name)
    name = None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if re.search(r"\b(?:NAME|APPLICANT NAME|NAMNE)\b", line, re.I) and not re.search(r"FATHER|HUSBAND", line, re.I):
            val = re.sub(r"^.*?\b(?:NAME|APPLICANT NAME|NAMNE)\b\s*[:/\-]?\s*", "", line, flags=re.I).strip()
            alpha_chars = sum(1 for c in val if c.isalpha())
            digit_chars = sum(1 for c in val if c.isdigit())
            if alpha_chars >= 3 and digit_chars <= 1 and not re.match(r"^[/:\- ]*$", val):
                name = val
            else:
                # Scan subsequent lines for the first line with real alphabetic name tokens
                for j in range(i + 1, min(i + 4, len(lines))):
                    cand = lines[j].strip()
                    c_alphas = sum(1 for c in cand if c.isalpha())
                    c_digits = sum(1 for c in cand if c.isdigit())
                    if c_alphas >= 3 and c_digits <= 1 and not re.search(r"FATHER|HUSBAND|DATE|DOB|INCOME|PERMANENT|GOVT|INDIA", cand, re.I):
                        name = cand
                        break
            break

    if not name:
        name_cand = _extract_after_label(text, ["APPLICANT NAME", "FULL NAME", "NAME"])
        if name_cand and sum(1 for c in name_cand if c.isalpha()) >= 3 and sum(1 for c in name_cand if c.isdigit()) <= 1:
            name = name_cand
    if name:
        fields["name"] = (name, _best_confidence(raw, name))

    # Father's Name
    father = None
    for i, line in enumerate(lines):
        if re.search(r"\b(?:FATHER'?S?\s*NAME|FATHER)\b", line, re.I):
            val = re.sub(r"^.*?\b(?:FATHER'?S?\s*NAME|FATHER)\b\s*[:/\-]?\s*", "", line, flags=re.I).strip()
            alpha_chars = sum(1 for c in val if c.isalpha())
            digit_chars = sum(1 for c in val if c.isdigit())
            if alpha_chars >= 3 and digit_chars <= 1 and not re.match(r"^[/:\- ]*$", val):
                father = val
            else:
                # Scan subsequent lines for the first line with real alphabetic name tokens
                for j in range(i + 1, min(i + 4, len(lines))):
                    cand = lines[j].strip()
                    c_alphas = sum(1 for c in cand if c.isalpha())
                    c_digits = sum(1 for c in cand if c.isdigit())
                    if c_alphas >= 3 and c_digits <= 1 and not re.search(r"DATE|DOB|BIRTH|INCOME|PERMANENT|SIGNATURE", cand, re.I):
                        father = cand
                        break
            break

    if not father:
        father = _extract_after_label(text, ["FATHER'S NAME", "FATHERS NAME", "FATHER NAME"])
    if father:
        fields["father_name"] = (father, _best_confidence(raw, father))

    # Date of Birth
    dob = _extract_date(text)
    if dob:
        fields["date_of_birth"] = (dob, _best_confidence(raw, dob))

    return fields, anchor_found

# ---------------------------------------------------------------------------
# Aadhaar Name Candidate Evaluator
# ---------------------------------------------------------------------------

def _evaluate_aadhaar_name_candidates(
    text: str,
    raw: RawResult,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Specifically selects the English (Latin script) Name line from Aadhaar OCR text.
    Handles stacked multilingual text (regional script line(s), then English),
    eliminating watermark text, photo design artifacts, and non-Latin scripts.

    Returns:
        (best_name, candidate_debug_list)
    """
    debug_candidates: List[Dict[str, Any]] = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 1. Identify anchor positions in lines
    dob_idx = -1
    gender_idx = -1
    aadhaar_num_idx = -1

    for idx, l in enumerate(lines):
        if dob_idx == -1 and re.search(r"\b(?:DOB|DATE OF BIRTH|YEAR OF BIRTH|YOB)\b|\b\d{2}[/\-.]\d{2}[/\-.]\d{4}\b", l, re.I):
            dob_idx = idx
        if gender_idx == -1 and re.search(r"\b(?:MALE|FEMALE|TRANSGENDER)\b", l, re.I):
            gender_idx = idx
        if aadhaar_num_idx == -1 and re.search(r"\b\d{4}\s+\d{4}\s+\d{4}\b", l):
            aadhaar_num_idx = idx

    header_pattern = re.compile(
        r"GOVERNMENT|INDIA|BHARAT|SARKAR|UNIQUE IDENTIFICATION|AUTHORITY|UIDAI|AADHAAR|"
        r"MERA AADHAAR|MERI PEHCHAAN|ENROLMENT|HELP@UIDAI|1947|WWW\.UIDAI|ISSUE DATE|"
        r"DOWNLOAD DATE|ELECTRONICALLY|SIGNATURE|VALID|DIGITALLY",
        re.I
    )
    watermark_pattern = re.compile(r"\b(?:PHOTO|SIGN|SIGNATURE|FINGERPRINT|OFF|QR|BARCODE|CARD|IDENTITY)\b", re.I)

    # 2. Gather candidate strings
    candidate_entries: List[Tuple[str, int, str]] = []  # (line_text, line_idx, source_type)

    # Check for explicit name label first
    for idx, line in enumerate(lines):
        m_label = re.match(r"^(?:FULL\s+)?NAME\s*[:\-]?\s*(.+)$", line, re.I)
        if m_label and not re.search(r"FATHER|MOTHER|HUSBAND|GUARDIAN|SPOUSE", line, re.I):
            candidate_entries.append((m_label.group(1).strip(), idx, "explicit_label"))

    # Name region is generally between card headers and DOB / Gender
    upper_bound = dob_idx if dob_idx != -1 else (gender_idx if gender_idx != -1 else len(lines))
    start_idx = 0
    for idx in range(min(upper_bound, len(lines))):
        if header_pattern.search(lines[idx]):
            start_idx = idx + 1

    # Add all lines in the name region
    for idx in range(start_idx, upper_bound):
        candidate_entries.append((lines[idx], idx, "name_region"))
        # Also add combined adjacent lines (e.g. "Thada" + "Sai Pragnay" -> "Thada Sai Pragnay")
        if idx + 1 < upper_bound:
            combined_pair = f"{lines[idx]} {lines[idx + 1]}".strip()
            candidate_entries.append((combined_pair, idx + 1, "combined_name_region"))

    # Fallback if no candidates between headers and DOB
    if not candidate_entries:
        for idx in range(start_idx, min(start_idx + 5, len(lines))):
            candidate_entries.append((lines[idx], idx, "fallback_region"))

    # 3. Score candidates
    scored_candidates = []
    seen_candidates = set()

    for cand_text, line_idx, source_type in candidate_entries:
        cand_clean = cand_text.strip()
        if len(cand_clean) < 3 or cand_clean in seen_candidates:
            continue
        seen_candidates.add(cand_clean)

        # Skip obvious headers, dates, or Aadhaar numbers
        if header_pattern.search(cand_clean) or re.search(r"\b\d{4}\s+\d{4}\s+\d{4}\b", cand_clean):
            continue
        if re.search(r"\b\d{2}[/\-.]\d{2}[/\-.]\d{4}\b", cand_clean):
            continue

        # Latin-script ratio: proportion of Latin alphabet chars [A-Za-z] among non-space chars
        latin_chars = sum(1 for c in cand_clean if ('A' <= c <= 'Z') or ('a' <= c <= 'z'))
        non_space = sum(1 for c in cand_clean if not c.isspace())
        latin_ratio = (latin_chars / non_space) if non_space > 0 else 0.0

        # Discard candidate immediately if contains virtually no Latin script (e.g. Devanagari Unicode)
        if latin_ratio < 0.60:
            debug_candidates.append({
                "candidate": cand_clean,
                "latin_ratio": round(latin_ratio, 2),
                "score": -100.0,
                "selected": False,
                "rejection_reason": "Non-Latin / Regional script (Devanagari/other) line"
            })
            continue

        # Clean into individual words
        raw_words = cand_clean.split()
        words = [re.sub(r"[^A-Za-z.'-]", "", w) for w in raw_words]
        words = [w for w in words if len(w) >= 2]
        word_count = len(words)

        if word_count == 0:
            continue

        # Base score from Latin character purity
        score = latin_ratio * 40.0

        # Word count heuristic
        if 2 <= word_count <= 4:
            score += 30.0  # Standard Indian name: 2-3 words
        elif word_count == 1:
            score += 10.0
        else:
            score -= 20.0

        # Capitalization heuristic (ALL-CAPS or Title Case)
        is_upper_or_title = all(w.isupper() or w.istitle() for w in words)
        if is_upper_or_title:
            score += 15.0

        # Proximity to DOB bonus (Aadhaar cards print name directly above DOB)
        if dob_idx != -1 and line_idx < dob_idx:
            distance = dob_idx - line_idx
            if distance == 1:
                score += 20.0  # Immediately above DOB
            elif distance == 2:
                score += 15.0  # Two lines above DOB
            elif distance <= 4:
                score += 5.0

        # Explicit label bonus
        if source_type == "explicit_label":
            score += 35.0

        # Penalty for digits or symbols in raw line
        digits_count = sum(1 for c in cand_clean if c.isdigit())
        if digits_count > 0:
            score -= (digits_count * 10.0)

        notes_reasons = []
        # Penalty for known watermark or OCR artifact words
        if watermark_pattern.search(cand_clean):
            score -= 30.0
            notes_reasons.append("Contains watermark/card noise keywords")

        # Specific guard for known garbled misreads like "POD FERD"
        if re.search(r"\b(?:POD|FERD|Ff|nl|Off3s|Zu|Rhy|crake)\b", cand_clean, re.I):
            score -= 40.0
            notes_reasons.append("Contains known OCR misread artifact token")

        # Vowel presence check (Indian Latin-script names have vowels in each word)
        vowel_pattern = re.compile(r"[AEIOUYaeiouy]")
        words_without_vowels = [w for w in words if len(w) >= 3 and not vowel_pattern.search(w)]
        if words_without_vowels:
            score -= 25.0
            notes_reasons.append(f"Word(s) lack vowels: {words_without_vowels}")

        scored_candidates.append({
            "candidate": " ".join(words).strip(),
            "raw_line": cand_clean,
            "latin_ratio": round(latin_ratio, 2),
            "word_count": word_count,
            "score": round(score, 1),
            "selected": False,
            "rejection_reason": "; ".join(notes_reasons) if notes_reasons else None
        })

    # 4. Select candidate with highest positive score
    best_name = None
    if scored_candidates:
        scored_candidates.sort(key=lambda c: c["score"], reverse=True)
        top = scored_candidates[0]
        if top["score"] > 0:
            top["selected"] = True
            best_name = top["candidate"]

    # Combine all debug candidates
    all_debug = scored_candidates + [c for c in debug_candidates if c not in scored_candidates]
    return best_name, all_debug


def _extract_aadhaar_fields(
    text: str,
    raw: RawResult,
    img: Optional[np.ndarray] = None
) -> Tuple[Dict[str, Tuple[str, float]], List[Dict[str, Any]]]:
    """
    Extracts structured fields from Aadhaar Card:
    - Aadhaar Number (4-4-4 format)
    - Name (specifically selects Latin-script English name from multilingual candidates)
    - Date of Birth / Year of Birth
    - Gender
    - Address (multi-line block)
    Returns (fields, name_debug_info).
    """
    fields: Dict[str, Tuple[str, float]] = {}

    # Aadhaar Number
    aadhaar_match = re.search(r"\b(\d{4}\s+\d{4}\s+\d{4})\b", text)
    if not aadhaar_match:
        aadhaar_match = re.search(r"\b(\d{12})\b", text)
        if aadhaar_match:
            d = aadhaar_match.group(1)
            aadhaar_no = f"{d[0:4]} {d[4:8]} {d[8:12]}"
        else:
            aadhaar_no = None
    else:
        aadhaar_no = aadhaar_match.group(1)

    if aadhaar_no:
        fields["aadhaar_number"] = (aadhaar_no, _best_confidence(raw, aadhaar_no))

    # DOB / YOB
    dob_match = re.search(r"(?:DOB|DATE OF BIRTH)\s*[:\-]?\s*(\d{2}[/\-.]\d{2}[/\-.]\d{4})", text, re.I)
    if dob_match:
        fields["date_of_birth"] = (dob_match.group(1), _best_confidence(raw, dob_match.group(1)))
    else:
        yob_match = re.search(r"(?:YEAR OF BIRTH|YOB)\s*[:\-]?\s*(\d{4})", text, re.I)
        if yob_match:
            fields["year_of_birth"] = (yob_match.group(1), _best_confidence(raw, yob_match.group(1)))
        else:
            gen_dob = _extract_date(text)
            if gen_dob:
                fields["date_of_birth"] = (gen_dob, _best_confidence(raw, gen_dob))

    # Gender
    if re.search(r"\b(?:FEMALE)\b", text, re.I):
        fields["gender"] = ("Female", 0.95)
    elif re.search(r"\b(?:MALE)\b", text, re.I):
        fields["gender"] = ("Male", 0.95)
    elif re.search(r"\b(?:TRANSGENDER)\b", text, re.I):
        fields["gender"] = ("Transgender", 0.95)

    # Name: Specifically select Latin-script English name from multilingual / stacked candidates
    name, name_debug_info = _evaluate_aadhaar_name_candidates(text, raw)
    if name:
        fields["name"] = (name, _best_confidence(raw, name))

    # Address (multi-line block)
    addr_match = re.search(r"(?:ADDRESS|PERMANENT ADDRESS)\s*[:\-]?\s*([\s\S]+?)(?=\b\d{4}\s+\d{4}\s+\d{4}\b|\b[A-Z0-9]{10}\b|\Z)", text, re.I)
    if addr_match:
        addr_text = " ".join(addr_match.group(1).split())
        fields["address"] = (addr_text[:200], _best_confidence(raw, addr_text[:30]))
    else:
        addr_val = _extract_after_label(text, ["ADDRESS", "RESIDENTIAL ADDRESS"], max_chars=160)
        if addr_val:
            fields["address"] = (addr_val, _best_confidence(raw, addr_val))

    return fields, name_debug_info


# ---------------------------------------------------------------------------
_INDIAN_STATES = (
    "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHHATTISGARH",
    "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JHARKHAND", "KARNATAKA",
    "KERALA", "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA", "MIZORAM",
    "NAGALAND", "ODISHA", "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU",
    "TELANGANA", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND", "WEST BENGAL", "DELHI",
    "JAMMU AND KASHMIR", "LADAKH", "PUDUCHERRY", "CHANDIGARH",
)


def _extract_voter_fields(text: str, raw: RawResult) -> Tuple[Dict[str, Tuple[str, float]], bool, Optional[bool]]:
    """
    Extracts structured fields from Voter ID (EPIC):
    - EPIC Number (3 letters + 7 digits)
    - Name
    - Father's/Husband's Name
    - Date of Birth or Age
    - Gender
    - Address
    - Issuing Authority anchor phrase check
    - Issuing State & address cross-check
    Returns (fields, anchor_found, state_address_match)
    """
    fields: Dict[str, Tuple[str, float]] = {}
    upper = text.upper()

    # Anchor check
    anchor_found = ("ELECTION COMMISSION" in upper) or ("BHARAT NIRVACHAN" in upper)
    if anchor_found:
        fields["issuing_authority"] = ("ELECTION COMMISSION OF INDIA", 0.95)

    # EPIC Number: 3 letters + 7 digits
    epic_match = re.search(r"\b([A-Z]{3}[0-9]{7})\b", upper)
    if epic_match:
        epic_no = epic_match.group(1)
        fields["epic_number"] = (epic_no, _best_confidence(raw, epic_no))
    else:
        val = _extract_after_label(text, ["EPIC NO", "EPIC NUMBER", "CARD NO", "IDENTITY CARD NO"])
        if val:
            fields["epic_number"] = (val, _best_confidence(raw, val))

    # Name
    name = _extract_after_label(text, ["ELECTOR'S NAME", "ELECTOR NAME", "NAME", "VOTER NAME"])
    if name:
        fields["name"] = (name, _best_confidence(raw, name))

    # Relation / Father's / Husband's Name
    rel_name = _extract_after_label(text, ["FATHER'S NAME", "FATHERS NAME", "FATHER NAME", "HUSBAND'S NAME", "HUSBAND NAME", "RELATION'S NAME"])
    if rel_name:
        fields["relation_name"] = (rel_name, _best_confidence(raw, rel_name))

    # DOB or Age
    dob = _extract_date(text)
    if dob:
        fields["date_of_birth"] = (dob, _best_confidence(raw, dob))
    else:
        age_match = re.search(r"\b(?:AGE|YEARS?)\s*[:\-]?\s*(\d{1,3})\b", text, re.I)
        if age_match:
            fields["age"] = (age_match.group(1), _best_confidence(raw, age_match.group(1)))

    # Gender
    if re.search(r"\b(?:FEMALE)\b", text, re.I):
        fields["gender"] = ("Female", 0.95)
    elif re.search(r"\b(?:MALE)\b", text, re.I):
        fields["gender"] = ("Male", 0.95)

    # Address
    addr = _extract_after_label(text, ["ADDRESS", "PERMANENT ADDRESS"], max_chars=160)
    if addr:
        fields["address"] = (addr, _best_confidence(raw, addr))

    # Issuing State from context (e.g. Chief Electoral Officer <State>)
    issuing_state = None
    state_match_m = re.search(
        r"(?:CHIEF ELECTORAL OFFICER|ELECTION COMMISSION OF INDIA)[,\s\-]+([A-Z\s]{3,30})",
        upper
    )
    if state_match_m:
        cand = state_match_m.group(1).strip()
        for state in _INDIAN_STATES:
            if state in cand:
                issuing_state = state.title()
                break
    if not issuing_state:
        for state in _INDIAN_STATES:
            if state in upper:
                issuing_state = state.title()
                break

    if issuing_state:
        fields["issuing_state"] = (issuing_state, 0.90)

    # Address cross-check: if state is visible and address is extracted
    state_address_match: Optional[bool] = None
    if issuing_state and "address" in fields:
        addr_upper = fields["address"][0].upper()
        state_address_match = issuing_state.upper() in addr_upper

    return fields, anchor_found, state_address_match



# ---------------------------------------------------------------------------
# Passport, Visa, and Other ID Extractors
# ---------------------------------------------------------------------------

def _extract_passport_fields(text: str, raw: RawResult) -> Dict[str, Tuple[str, float]]:
    fields: Dict[str, Tuple[str, float]] = {}

    name = _extract_after_label(text, ["SURNAME / NOM", "SURNAME", "LAST NAME", "NAME"])
    if name:
        fields["name"] = (name, _best_confidence(raw, name))
        fields["surname"] = (name, _best_confidence(raw, name))

    given = _extract_after_label(text, ["GIVEN NAMES / PRÉNOMS", "GIVEN NAMES / PRENOMS", "GIVEN NAMES", "GIVEN NAME", "FIRST NAME"])
    if given:
        fields["given_names"] = (given, _best_confidence(raw, given))

    pno = _extract_after_label(text, ["PASSPORT NO. / NO. DU PASSEPORT", "PASSPORT NO", "PASSPORT NUMBER", "DOCUMENT NO"])
    if not pno:
        m = re.search(r"\b[A-Z][0-9]{7,8}\b", text)
        if m:
            pno = m.group(0)
    if pno:
        fields["passport_number"] = (pno.strip(), _best_confidence(raw, pno))

    nat = _extract_after_label(text, ["NATIONALITY / NATIONALITÉ", "NATIONALITY / NATIONALITE", "NATIONALITY", "NATION"])
    if not nat:
        m = re.search(r"\b(UTO|INDIAN|AMERICAN|BRITISH|FRENCH|GERMAN|EMIRATI|CANADIAN|AUSTRALIAN)\b", text, re.I)
        if m:
            nat = m.group(0).upper()
    if nat:
        fields["nationality"] = (nat.strip(), _best_confidence(raw, nat))

    dob_ctx = _extract_after_label(text, ["DATE OF BIRTH / DATE DE NAISSANCE", "DATE OF BIRTH", "DOB", "BIRTH DATE"])
    dob = _extract_date(dob_ctx or text)
    if dob:
        fields["date_of_birth"] = (dob, _best_confidence(raw, dob))

    exp_ctx = _extract_after_label(text, ["DATE OF EXPIRY / DATE D'EXPIRATION", "DATE OF EXPIRY", "EXPIRY DATE", "VALID UNTIL", "EXPIRATION"])
    exp = _extract_date(exp_ctx or "")
    if not exp:
        dates = re.findall(r"\b\d{2}[/\-.]\d{2}[/\-.]\d{4}\b", text)
        exp = dates[-1] if len(dates) >= 2 else None
    if exp:
        fields["date_of_expiry"] = (exp, _best_confidence(raw, exp))

    gender_match = re.search(r"\b(?:SEX / SEXE|SEX|GENDER)\s*[:\-]?\s*([MF]|MALE|FEMALE)\b", text, re.I)
    if gender_match:
        g = gender_match.group(1).upper()
        fields["sex"] = (g if g in ("M", "F") else ("F" if g == "FEMALE" else "M"), 0.95)
        fields["gender"] = ("Female" if g in ("F", "FEMALE") else "Male", 0.95)

    poi = _extract_after_label(text, ["PLACE OF ISSUE", "PLACE OF ISSUANCE", "ISSUED AT", "ISSUED BY"])
    if poi:
        fields["place_of_issue"] = (poi.strip(), _best_confidence(raw, poi))

    return fields


def _extract_visa_fields(text: str, raw: RawResult) -> Dict[str, Tuple[str, float]]:
    fields: Dict[str, Tuple[str, float]] = {}

    vno = _extract_after_label(text, ["VISA NUMBER / NO. DU VISA", "VISA NO", "VISA NUMBER", "FOLIO NO"])
    if not vno:
        m = re.search(r"\bV[0-9]{7,10}\b", text)
        if m:
            vno = m.group(0)
        else:
            m2 = re.search(r"\b[A-Z0-9]{7,12}\b", text)
            vno = m2.group(0) if m2 else None
    if vno:
        fields["visa_number"] = (vno.strip(), _best_confidence(raw, vno))

    name = _extract_after_label(text, ["FULL NAME / NOM COMPLET", "FULL NAME", "NAME", "NOM"])
    if name:
        fields["name"] = (name, _best_confidence(raw, name))
        if "," in name:
            parts = name.split(",", 1)
            fields["surname"] = (parts[0].strip(), _best_confidence(raw, parts[0].strip()))
            fields["given_names"] = (parts[1].strip(), _best_confidence(raw, parts[1].strip()))

    pno = _extract_after_label(text, ["PASSPORT NO / NO DU PASSEPORT", "PASSPORT NO", "PASSPORT NUMBER"])
    if not pno:
        m = re.search(r"\bU[0-9]{7,10}\b", text)
        if m:
            pno = m.group(0)
    if pno:
        fields["passport_number"] = (pno.strip(), _best_confidence(raw, pno))

    nat = _extract_after_label(text, ["NATIONALITY / NATIONALITÉ", "NATIONALITY / NATIONALITE", "NATIONALITY", "NATION"])
    if not nat:
        m = re.search(r"\b(UTO|INDIAN|AMERICAN|BRITISH|FRENCH|GERMAN|EMIRATI|CANADIAN|AUSTRALIAN)\b", text, re.I)
        if m:
            nat = m.group(0).upper()
    if nat:
        fields["nationality"] = (nat.strip(), _best_confidence(raw, nat))

    dob_ctx = _extract_after_label(text, ["DATE OF BIRTH / DATE DE NAISSANCE", "DATE OF BIRTH", "DOB"])
    dob = _extract_date(dob_ctx or text)
    if dob:
        fields["date_of_birth"] = (dob, _best_confidence(raw, dob))

    gender_match = re.search(r"\b(?:SEX / SEXE|SEX|GENDER)\s*[:\-]?\s*([MF]|MALE|FEMALE)\b", text, re.I)
    if gender_match:
        g = gender_match.group(1).upper()
        fields["sex"] = (g if g in ("M", "F") else ("F" if g == "FEMALE" else "M"), 0.95)
        fields["gender"] = ("Female" if g in ("F", "FEMALE") else "Male", 0.95)

    valid_from = _extract_after_label(text, ["VALID FROM / VALIDE DU", "VALID FROM", "ENTRY FROM", "ISSUE DATE"])
    if valid_from:
        d = _extract_date(valid_from)
        if d:
            fields["valid_from"] = (d, _best_confidence(raw, d))

    valid_until = _extract_after_label(text, ["DATE OF EXPIRY / DATE D'EXPIRATION", "DATE OF EXPIRY", "EXPIRY", "VALID UNTIL", "VALID TO"])
    if valid_until:
        d = _extract_date(valid_until)
        if d:
            fields["valid_until"] = (d, _best_confidence(raw, d))
            fields["date_of_expiry"] = (d, _best_confidence(raw, d))

    vtype = _extract_after_label(text, ["VISA TYPE", "VISA CATEGORY", "TYPE"])
    if vtype:
        fields["visa_type"] = (vtype.strip(), _best_confidence(raw, vtype))

    stay = _extract_after_label(text, ["DURATION OF STAY", "STAY", "DAYS"])
    if stay:
        fields["stay_duration"] = (stay.strip()[:30], _best_confidence(raw, stay))

    country = _extract_after_label(text, ["ISSUING COUNTRY", "ISSUED BY", "COUNTRY"])
    if country:
        fields["issuing_country"] = (country.strip(), _best_confidence(raw, country))

    return fields


def _extract_id_fields(text: str, raw: RawResult, doc_type: str) -> Dict[str, Tuple[str, float]]:
    """Shared extractor for driving_license, permit, and generic national_id."""
    fields: Dict[str, Tuple[str, float]] = {}

    name = _extract_after_label(text, ["NAME", "FULL NAME", "HOLDER"])
    if name:
        fields["name"] = (name.strip(), _best_confidence(raw, name))

    id_no = _extract_after_label(
        text, ["ID NO", "ID NUMBER", "LICENSE NO", "LICENCE NO",
               "DL NO", "PERMIT NO", "DOCUMENT NO", "AADHAAR NO"]
    )
    if not id_no:
        m = re.search(r"\b[A-Z]{2}[0-9]{2,4}[A-Z0-9]{5,10}\b", text)
        id_no = m.group(0) if m else None
    if id_no:
        fields["id_number"] = (id_no.strip(), _best_confidence(raw, id_no))

    dob_ctx = _extract_after_label(text, ["DATE OF BIRTH", "DOB", "BIRTH DATE", "D.O.B"])
    dob = _extract_date(dob_ctx or text)
    if dob:
        fields["date_of_birth"] = (dob, _best_confidence(raw, dob))

    addr = _extract_after_label(
        text, ["ADDRESS", "PERMANENT ADDRESS", "RESIDENTIAL ADDRESS"], max_chars=120
    )
    if addr:
        fields["address"] = (addr.strip()[:120], _best_confidence(raw, addr))

    exp_ctx = _extract_after_label(text, ["EXPIRY", "VALID TILL", "VALID UNTIL", "EXPIRATION DATE"])
    exp = _extract_date(exp_ctx or "")
    if exp:
        fields["expiry"] = (exp, _best_confidence(raw, exp))

    return fields


# ---------------------------------------------------------------------------
# Public Dispatcher
# ---------------------------------------------------------------------------

def extract_fields(
    img: np.ndarray,
    doc_type: str,
    precomputed_text: Optional[str] = None,
    precomputed_raw: Optional[RawResult] = None,
) -> Tuple[Dict[str, Tuple[str, float]], str, Dict[str, any]]:
    """
    Run OCR on image and extract structured fields for the specified document type.
    Uses precomputed text and tokens if provided (instant 0.1ms extraction).

    Returns:
        (fields_dict, raw_ocr_text, extra_metadata)
    """
    if precomputed_text is not None and precomputed_raw is not None:
        text, raw = precomputed_text, precomputed_raw
    else:
        lang = "en"
        text, raw = extract_raw_text(img, lang=lang)

    extra_meta: Dict[str, any] = {}

    if doc_type == "national_id_pan":
        fields, anchor_found = _extract_pan_fields(text, raw)
        extra_meta["anchor_found"] = anchor_found
    elif doc_type == "national_id_aadhaar":
        fields, name_debug_info = _extract_aadhaar_fields(text, raw, img)
        extra_meta["name_debug_info"] = name_debug_info
    elif doc_type == "national_id_voter":
        fields, anchor_found, state_address_match = _extract_voter_fields(text, raw)
        extra_meta["anchor_found"] = anchor_found
        if state_address_match is not None:
            extra_meta["state_address_match"] = state_address_match

    elif doc_type == "passport":
        fields = _extract_passport_fields(text, raw)
    elif doc_type == "visa":
        fields = _extract_visa_fields(text, raw)
    else:
        fields = _extract_id_fields(text, raw, doc_type)

    return fields, text, extra_meta


# ---------------------------------------------------------------------------
# Region-Based Layout Extractor (Optimized Fast Path)
# ---------------------------------------------------------------------------

def extract_fields_region_based(
    img: np.ndarray,
    doc_type: str,
    back_img: Optional[np.ndarray] = None,
    precomputed_text: Optional[str] = None,
    precomputed_raw: Optional[RawResult] = None,
    precomputed_hdr_text: Optional[str] = None,
    precomputed_hdr_raw: Optional[RawResult] = None,
) -> Tuple[Dict[str, Tuple[str, float]], str, Dict[str, any], List[str]]:
    """
    High-speed region-based field extraction:
    1. If precomputed OCR tokens are available from single-pass extraction, extracts
       fields directly in sub-millisecond time with zero redundant neural inferences.
    2. Otherwise crops expected regions according to layout templates.
    """
    notes: List[str] = []
    extra_meta: Dict[str, any] = {}

    # Fast path: Precomputed global single-pass OCR tokens
    if precomputed_text is not None and precomputed_raw is not None:
        fields, text, extra_meta = extract_fields(
            img, doc_type, precomputed_text=precomputed_text, precomputed_raw=precomputed_raw
        )
        # Check if address should be extracted from back image
        if back_img is not None and "address" not in fields:
            b_text, b_raw = extract_raw_text(back_img)
            if b_text.strip():
                addr_match = re.search(r"(?:ADDRESS|PERMANENT ADDRESS)\s*[:\-]?\s*([\s\S]+?)(?=\b\d{4}\s+\d{4}\s+\d{4}\b|\b[A-Z0-9]{10}\b|\Z)", b_text, re.I)
                if addr_match:
                    addr_cleaned = " ".join(addr_match.group(1).split())
                    fields["address"] = (addr_cleaned[:200], _best_confidence(b_raw, addr_cleaned[:30]))
                else:
                    addr_lines = [l.strip() for l in b_text.splitlines() if len(l.strip()) > 3 and not re.search(r"HELP@UIDAI|WWW\.UIDAI|1947", l, re.I)]
                    if addr_lines:
                        clean_addr = ", ".join(addr_lines)
                        fields["address"] = (clean_addr[:200], 0.85)

        return fields, text, extra_meta, notes

    from .layout_templates import get_layout_template, crop_region
    from .preprocessing import denoise_patch
    from .ocr_engine import extract_single_line

    template = get_layout_template(doc_type)

    if template is None:
        fields, text, meta = extract_fields(img, doc_type)
        return fields, text, meta, notes

    fields: Dict[str, Tuple[str, float]] = {}
    crop_texts: List[str] = []
    extra_meta: Dict[str, any] = {}

    h, w = img.shape[:2]

    # --- PAN Card Layout ---
    if doc_type == "national_id_pan":
        # 1. Header region
        anchor_found = False
        if precomputed_hdr_text:
            crop_texts.append(precomputed_hdr_text)
            upper_hdr = precomputed_hdr_text.upper()
            anchor_found = "INCOME TAX" in upper_hdr or "GOVT OF INDIA" in upper_hdr or "GOVERNMENT OF INDIA" in upper_hdr
            extra_meta["anchor_found"] = anchor_found
            if anchor_found:
                fields["issuing_authority"] = ("INCOME TAX DEPARTMENT, GOVT OF INDIA", 0.95)
        elif "header" in template:
            hdr_patch, _ = crop_region(img, template["header"])
            hdr_text, hdr_raw = extract_raw_text(hdr_patch)
            crop_texts.append(hdr_text)
            upper_hdr = hdr_text.upper()
            anchor_found = "INCOME TAX" in upper_hdr or "GOVT OF INDIA" in upper_hdr or "GOVERNMENT OF INDIA" in upper_hdr
            extra_meta["anchor_found"] = anchor_found
            if anchor_found:
                fields["issuing_authority"] = ("INCOME TAX DEPARTMENT, GOVT OF INDIA", 0.95)

        # 2. Consolidated Card Body region (PAN, Name, Father's Name, DOB in one high-speed pass)
        if "body" in template:
            body_patch, _ = crop_region(img, template["body"])
            b_text, b_raw = extract_raw_text(body_patch)
            crop_texts.append(b_text)
            pan_fields, body_anchor = _extract_pan_fields(b_text, b_raw)
            for k, v in pan_fields.items():
                fields[k] = v
            if (body_anchor or anchor_found) and "issuing_authority" not in fields:
                fields["issuing_authority"] = ("INCOME TAX DEPARTMENT, GOVT OF INDIA", 0.95)

        # Fallback to individual PAN strip if pan_number missed in body crop
        if "pan_number" not in fields and "pan_number" in template:
            pan_patch, _ = crop_region(img, template["pan_number"])
            p_text, p_raw = extract_raw_text(pan_patch)
            crop_texts.append(p_text)
            m = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", p_text.upper())
            if m:
                pan_val = m.group(0)
                conf = _best_confidence(p_raw, pan_val)
                fields["pan_number"] = (pan_val, conf)

    # --- Aadhaar Card Layout ---
    elif doc_type == "national_id_aadhaar":
        # Check if precomputed header text already contains name & DOB (e.g. Padigela Srija)
        if precomputed_hdr_text and precomputed_hdr_raw:
            crop_texts.append(precomputed_hdr_text)
            hdr_aadhaar, hdr_dbg = _extract_aadhaar_fields(precomputed_hdr_text, precomputed_hdr_raw, img)
            for k, v in hdr_aadhaar.items():
                fields[k] = v
            if hdr_dbg:
                extra_meta["name_debug_info"] = hdr_dbg

        # 1. Consolidated info block (Name, DOB, Gender in one high-speed pass)
        if ("name" not in fields or "date_of_birth" not in fields) and "info_block" in template:
            info_patch, _ = crop_region(img, template["info_block"])
            i_text, i_raw = extract_raw_text(info_patch)
            crop_texts.append(i_text)
            aadhaar_fields, name_debug_info = _extract_aadhaar_fields(i_text, i_raw, info_patch)
            for k, v in aadhaar_fields.items():
                if k not in fields or fields[k][1] < v[1]:
                    fields[k] = v
            if name_debug_info:
                extra_meta["name_debug_info"] = name_debug_info

        # 2. Aadhaar 12-digit UID region
        if "aadhaar_number" in template:
            a_patch, _ = crop_region(img, template["aadhaar_number"])
            a_text, a_raw = extract_raw_text(a_patch)
            crop_texts.append(a_text)
            m = re.search(r"\b(\d{4})\s*(\d{4})\s*(\d{4})\b", a_text)
            if m:
                uid_str = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                conf = _best_confidence(a_raw, m.group(1))
                if conf < 0.55:
                    d_patch = denoise_patch(a_patch)
                    _, d_raw = extract_raw_text(d_patch)
                    d_conf = _best_confidence(d_raw, m.group(1))
                    conf = max(conf, d_conf)
                fields["aadhaar_number"] = (uid_str, round(max(conf, 0.70), 3))

        # 3. Address region (from back image if provided)
        target_address_img = back_img if back_img is not None else img
        if "address" in template and back_img is not None:
            addr_patch, _ = crop_region(target_address_img, template["address"])
            addr_text, addr_raw = extract_raw_text(addr_patch)
            crop_texts.append(addr_text)
            if addr_text.strip():
                addr_match = re.search(r"(?:ADDRESS|PERMANENT ADDRESS)\s*[:\-]?\s*([\s\S]+?)(?=\b\d{4}\s+\d{4}\s+\d{4}\b|\b[A-Z0-9]{10}\b|\Z)", addr_text, re.I)
                if addr_match:
                    addr_cleaned = " ".join(addr_match.group(1).split())
                    fields["address"] = (addr_cleaned[:200], _best_confidence(addr_raw, addr_cleaned[:30]))
                else:
                    addr_lines = [l.strip() for l in addr_text.splitlines() if len(l.strip()) > 3 and not re.search(r"HELP@UIDAI|WWW\.UIDAI|1947", l, re.I)]
                    clean_addr = ", ".join(addr_lines)
                    conf = 0.85 if len(clean_addr) > 20 else 0.65
                    fields["address"] = (clean_addr, conf)

    # --- Passport / Visa / General ---
    else:
        # Fallback to standard field extractor for passport/visa visual fields
        fields, text, extra_meta = extract_fields(img, doc_type)
        return fields, text, extra_meta, notes

    # Check completeness: If critical fields are missing, run full image fallback
    required_key = "pan_number" if doc_type == "national_id_pan" else ("aadhaar_number" if doc_type == "national_id_aadhaar" else "name")
    if required_key not in fields or len(fields) < 2:
        notes.append(f"Region-based crop missed {required_key}; running full-frame visual fallback.")
        fb_fields, fb_text, fb_meta = extract_fields(img, doc_type)
        for k, v in fb_fields.items():
            if k not in fields or fields[k][1] < v[1]:
                fields[k] = v
        combined_text = (fb_text + "\n" + "\n".join(crop_texts)).strip()
        return fields, combined_text, fb_meta, notes

    combined_text = "\n".join(crop_texts).strip()
    return fields, combined_text, extra_meta, notes

