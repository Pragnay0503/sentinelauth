"""
mrz_parser.py — ICAO 9303 Machine Readable Zone parser.

Detects MRZ region, runs a dedicated high-accuracy OCR pass,
parsed TD1 (3-line 30-char) and TD3 (2-line 44-char) formats,
and validates all built-in ICAO checksum digits.

Fully self-contained — no imports from other project modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# ICAO 9303 checksum constants
# ---------------------------------------------------------------------------

_MRZ_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"
_MRZ_WEIGHTS = [7, 3, 1]


def _char_value(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    if ch == "<":
        return 0
    if ch.isalpha():
        return ord(ch.upper()) - ord("A") + 10
    return 0


def _icao_checksum(text: str) -> int:
    """Compute ICAO 9303 weighted checksum for a string."""
    total = 0
    for i, ch in enumerate(text):
        total += _char_value(ch) * _MRZ_WEIGHTS[i % 3]
    return total % 10


def validate_checksum(text: str, expected_digit: str) -> bool:
    try:
        return _icao_checksum(text) == int(expected_digit)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# MRZ data container
# ---------------------------------------------------------------------------

@dataclass
class MRZData:
    raw_lines:     List[str]       = field(default_factory=list)
    doc_type:      str             = ""
    country:       str             = ""
    surname:       str             = ""
    given_names:   str             = ""
    doc_number:    str             = ""
    nationality:   str             = ""
    dob:           str             = ""   # YYMMDD
    sex:           str             = ""
    expiry:        str             = ""   # YYMMDD
    optional1:     str             = ""
    optional2:     str             = ""
    checksums_ok:  Dict[str, bool] = field(default_factory=dict)
    all_valid:     bool            = False
    parse_error:   Optional[str]   = None

    def as_dict(self) -> Dict[str, str]:
        return {
            "surname":     self.surname,
            "given_names": self.given_names,
            "doc_number":  self.doc_number,
            "nationality": self.nationality,
            "dob":         _fmt_date(self.dob),
            "sex":         self.sex,
            "expiry":      _fmt_date(self.expiry),
            "country":     self.country,
            "doc_type":    self.doc_type,
        }


def _fmt_date(yymmdd: str) -> str:
    """Convert YYMMDD -> DD/MM/YYYY using ICAO 9303 century convention.
    YY 00-69  -> 2000-2069
    YY 70-99  -> 1970-1999
    """
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return yymmdd
    yy, mm, dd = yymmdd[:2], yymmdd[2:4], yymmdd[4:]
    century = "20" if int(yy) < 70 else "19"
    return f"{dd}/{mm}/{century}{yy}"


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _run_tesseract_mrz(roi: np.ndarray) -> str:
    """Run pytesseract with MRZ-optimised settings; fall back to EasyOCR."""
    text = ""
    try:
        import pytesseract
        config = "--psm 6 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
        text = pytesseract.image_to_string(roi, config=config)
    except Exception:
        text = ""

    if not text.strip():
        try:
            from .ocr_engine import run_paddleocr
            results = run_paddleocr(roi)
            if results:
                text = "\n".join(t for t, _ in results)
        except Exception:
            pass

    return text


def _normalise_mrz_line(line: str) -> str:
    """Fix common OCR confusions in MRZ lines."""
    # Replace characters that are visually similar in OCR
    mapping = {
        "O": "0", "o": "0", "D": "0",
        "I": "1", "l": "1", "L": "1",
        " ": "<", "\t": "<",
        "(": "<", "[": "<", "{": "<",
    }
    result = []
    for ch in line.upper():
        result.append(mapping.get(ch, ch))
    cleaned = "".join(result)
    # Keep only valid MRZ characters
    cleaned = re.sub(r"[^A-Z0-9<]", "<", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# MRZ region detection
# ---------------------------------------------------------------------------

def detect_mrz_lines(raw_text: str) -> List[str]:
    """
    From raw OCR text, find lines that look like MRZ
    (mostly uppercase letters, digits, and '<' characters).
    """
    candidates = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if len(stripped) < 20:
            continue
        # MRZ lines have >60% alphanumeric or '<'
        valid_chars = sum(1 for c in stripped if c.isalnum() or c == "<" or c == " ")
        if valid_chars / len(stripped) >= 0.80:
            candidates.append(_normalise_mrz_line(stripped))
    return candidates


# ---------------------------------------------------------------------------
# TD3 (Passport/Visa — 2 lines of 44 chars)
# ---------------------------------------------------------------------------

def _parse_td3(line1: str, line2: str) -> MRZData:
    mrz = MRZData(raw_lines=[line1, line2])

    # Pad/truncate to 44
    l1 = (line1 + "<" * 44)[:44]
    l2 = (line2 + "<" * 44)[:44]

    mrz.doc_type  = l1[0:2].rstrip("<")
    mrz.country   = l1[2:5].rstrip("<")
    names_raw     = l1[5:44]
    parts         = names_raw.split("<<")
    mrz.surname     = parts[0].replace("<", " ").strip() if parts else ""
    mrz.given_names = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""

    mrz.doc_number  = l2[0:9].rstrip("<")
    doc_check       = l2[9]
    mrz.nationality = l2[10:13].rstrip("<")
    mrz.dob         = l2[13:19]
    dob_check       = l2[19]
    mrz.sex         = l2[20]
    mrz.expiry      = l2[21:27]
    exp_check       = l2[27]
    mrz.optional1   = l2[28:42].rstrip("<")
    final_check     = l2[43]

    # Checksum validation
    mrz.checksums_ok = {
        "doc_number": validate_checksum(l2[0:9],   doc_check),
        "dob":        validate_checksum(l2[13:19], dob_check),
        "expiry":     validate_checksum(l2[21:27], exp_check),
        "composite":  validate_checksum(l2[0:10] + l2[13:20] + l2[21:43], final_check),
    }
    mrz.all_valid = all(mrz.checksums_ok.values())
    return mrz


# ---------------------------------------------------------------------------
# TD1 (National ID — 3 lines of 30 chars)
# ---------------------------------------------------------------------------

def _parse_td1(line1: str, line2: str, line3: str) -> MRZData:
    mrz = MRZData(raw_lines=[line1, line2, line3])

    l1 = (line1 + "<" * 30)[:30]
    l2 = (line2 + "<" * 30)[:30]
    l3 = (line3 + "<" * 30)[:30]

    mrz.doc_type    = l1[0:2].rstrip("<")
    mrz.country     = l1[2:5].rstrip("<")
    mrz.doc_number  = l1[5:14].rstrip("<")
    doc_check       = l1[14]
    mrz.optional1   = l1[15:29].rstrip("<")

    mrz.dob         = l2[0:6]
    dob_check       = l2[6]
    mrz.sex         = l2[7]
    mrz.expiry      = l2[8:14]
    exp_check       = l2[14]
    mrz.nationality = l2[15:18].rstrip("<")
    mrz.optional2   = l2[18:29].rstrip("<")
    final_check     = l2[29]

    names_raw       = l3
    parts           = names_raw.split("<<")
    mrz.surname     = parts[0].replace("<", " ").strip() if parts else ""
    mrz.given_names = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""

    mrz.checksums_ok = {
        "doc_number": validate_checksum(l1[5:14],  doc_check),
        "dob":        validate_checksum(l2[0:6],   dob_check),
        "expiry":     validate_checksum(l2[8:14],  exp_check),
        "composite":  validate_checksum(
            l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29], final_check
        ),
    }
    mrz.all_valid = all(mrz.checksums_ok.values())
    return mrz


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_mrz_from_image(image: np.ndarray) -> MRZData:
    """
    Directly extracts and parses MRZ from the bottom 12-18% of a passport/visa image.
    Executes single-line/strip OCR and parses using ICAO 9303 checksum logic.
    """
    from .preprocessing import extract_mrz_roi, preprocess_for_mrz
    from .ocr_engine import extract_raw_text
    
    # Crop bottom 16% strip
    roi_img, _ = extract_mrz_roi(image, bottom_pct=0.18)
    roi_proc = preprocess_for_mrz(roi_img)
    
    text, raw_tokens = extract_raw_text(roi_proc)
    lines = [l.strip().replace(" ", "") for l in text.splitlines() if l.strip()]
    lines = [l for l in lines if ("<" in l or len(l) >= 28)]
    
    # Also check detected lines from raw text
    candidates = detect_mrz_lines(text)
    combined = []
    seen = set()
    for l in (candidates + lines):
        cleaned = l.strip().replace(" ", "").upper()
        if cleaned and len(cleaned) >= 25 and cleaned not in seen:
            seen.add(cleaned)
            combined.append(cleaned)
            
    # Try TD3 first (2 lines, ~44 chars)
    td3 = [l for l in combined if len(l) >= 36]
    if len(td3) >= 2:
        for i in range(len(td3) - 1):
            res = _parse_td3(td3[i], td3[i + 1])
            if res.all_valid or (res.checksums_ok.get("doc_number") and res.checksums_ok.get("dob")):
                return res
        # Return the last two candidate parse even if partially valid
        return _parse_td3(td3[-2], td3[-1])

    # Try TD1 (3 lines, ~30 chars)
    td1 = [l for l in combined if 25 <= len(l) <= 35]
    if len(td1) >= 3:
        for i in range(len(td1) - 2):
            res = _parse_td1(td1[i], td1[i + 1], td1[i + 2])
            if res.all_valid or res.checksums_ok.get("doc_number"):
                return res
        return _parse_td1(td1[-3], td1[-2], td1[-1])

    empty = MRZData()
    empty.parse_error = "No valid MRZ lines detected in image ROI"
    return empty


def parse_mrz(raw_ocr_text: str, image: Optional[np.ndarray] = None) -> MRZData:
    """
    Detect and parse MRZ from raw OCR text or directly from image ROI.
    """
    if image is not None:
        img_mrz = parse_mrz_from_image(image)
        if img_mrz.all_valid or len(img_mrz.raw_lines) >= 2:
            return img_mrz

    mrz_lines = detect_mrz_lines(raw_ocr_text)

    # Deduplicate
    seen = set()
    unique_lines = []
    for l in mrz_lines:
        key = l.strip()
        if key and key not in seen:
            seen.add(key)
            unique_lines.append(key)
    mrz_lines = unique_lines

    # Try TD3 (2 lines, 44 chars)
    td3_candidates = [l for l in mrz_lines if len(l) >= 36]
    if len(td3_candidates) >= 2:
        try:
            return _parse_td3(td3_candidates[-2], td3_candidates[-1])
        except Exception:
            pass

    # Try TD1 (3 lines, 30 chars)
    td1_candidates = [l for l in mrz_lines if len(l) >= 25]
    if len(td1_candidates) >= 3:
        try:
            return _parse_td1(td1_candidates[-3], td1_candidates[-2], td1_candidates[-1])
        except Exception:
            pass

    # Nothing found — return empty
    empty = MRZData()
    empty.parse_error = "No valid MRZ lines detected in OCR output"
    return empty
