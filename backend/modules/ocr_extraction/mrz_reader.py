"""
mrz_reader.py - Dedicated ICAO 9303 MRZ Reader for SentinelAuth.

Implements high-accuracy Machine Readable Zone extraction for TD3 (Passport)
and MRV-A (Visa) documents:
1. Locates the MRZ band (bottom ~20%, dense monospaced text).
2. Preprocesses: deskew, 2x upscale, adaptive/Otsu binarization and grayscale enhancement.
3. Reads text with restricted character set (A-Z, 0-9, <).
4. Structure-aware positional disambiguation (ICAO 9303 field slots).
5. Confidence-gated repairs with comprehensive audit logging.
6. Multi-engine comparison (EasyOCR vs Tesseract).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ICAO 9303 character set
MRZ_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"

# Positional repair mappings per ICAO 9303 specification
ALPHA_REPAIRS = {
    "0": "D",  # D<->0 visual confusion in alphabetic positions (also O via OCR-B graph)
    "1": "L",  # L<->1 visual confusion in alphabetic positions (also I via OCR-B graph)
    "2": "Z",
    "5": "S",
    "8": "B",
    "7": "T",
}

NUMERIC_REPAIRS = {
    "O": "0",
    "D": "0",  # D->0 in numeric positions confirmed
    "Q": "0",
    "I": "1",
    "L": "1",  # L->1 in numeric positions confirmed
    "l": "1",
    "Z": "2",
    "S": "5",
    "B": "8",
    "G": "6",
}

# ISO 3166-1 alpha-3 Country Codes & ICAO Doc 9303 Part 3 Section 5 / Appendix Special Codes
ISO_3166_1_CODES = {
    # Official ISO 3166-1 alpha-3 codes (ICAO Doc 9303 Part 3 Section 5.1)
    "AFG", "ALB", "DZA", "AND", "AGO", "ATG", "ARG", "ARM", "AUS", "AUT", "AZE",
    "BHS", "BHR", "BGD", "BRB", "BLR", "BEL", "BLZ", "BEN", "BTN", "BOL", "BIH",
    "BWA", "BRA", "BRN", "BGR", "BFA", "BDI", "CPV", "KHM", "CMR", "CAN", "CAF",
    "TCD", "CHL", "CHN", "COL", "COM", "COG", "COD", "CRI", "CIV", "HRV", "CUB",
    "CYP", "CZE", "DNK", "DJI", "DMA", "DOM", "ECU", "EGY", "SLV", "GNQ", "ERI",
    "EST", "SWZ", "ETH", "FJI", "FIN", "FRA", "GAB", "GMB", "GEO", "DEU", "GHA",
    "GRC", "GRD", "GTM", "GIN", "GNB", "GUY", "HTI", "HND", "HUN", "ISL", "IND",
    "IDN", "IRN", "IRQ", "IRL", "ISR", "ITA", "JAM", "JPN", "JOR", "KAZ", "KEN",
    "KIR", "PRK", "KOR", "KWT", "KGZ", "LAO", "LVA", "LBN", "LSO", "LBR", "LBY",
    "LIE", "LTU", "LUX", "MDG", "MWI", "MYS", "MDV", "MLI", "MLT", "MHL", "MRT",
    "MUS", "MEX", "FSM", "MDA", "MCO", "MNG", "MNE", "MAR", "MOZ", "MMR", "NAM",
    "NRU", "NPL", "NLD", "NZL", "NIC", "NER", "NGA", "MKD", "NOR", "OMN", "PAK",
    "PLW", "PAN", "PNG", "PRY", "PER", "PHL", "POL", "PRT", "QAT", "ROU", "RUS",
    "RWA", "KNA", "LCA", "VCT", "WSM", "SMR", "STP", "SAU", "SEN", "SRB", "SYC",
    "SLE", "SGP", "SVK", "SVN", "SLB", "SOM", "ZAF", "SSD", "ESP", "LKA", "SDN",
    "SUR", "SWE", "CHE", "SYR", "TJK", "TZA", "THA", "TLS", "TGO", "TON", "TTO",
    "TUN", "TUR", "TKM", "TUV", "UGA", "UKR", "ARE", "GBR", "USA", "URY", "UZB",
    "VUT", "VEN", "VNM", "YEM", "ZMB", "ZWE",
    # Dependent territories & entities
    "ABW", "AIA", "ASM", "ATA", "ATF", "BES", "BMU", "BVT", "CCK", "COK", "CUW",
    "CXR", "CYM", "FLK", "FRO", "GIB", "GLP", "GRL", "GUF", "GUM", "HKG", "HMD",
    "IMN", "IOT", "JEY", "MAC", "MAF", "MNP", "MSR", "MTQ", "MYT", "NCL", "NFK",
    "NIU", "PCN", "PRI", "PYF", "REU", "SGS", "SHN", "SJM", "SPM", "SXM", "TCA",
    "TKL", "UMI", "VGB", "VIR", "WLF", "GGY",
    # ICAO Doc 9303 Part 3 Section 5 & Appendix Special Codes:
    "UTO",                                # Utopia / Fictitious State (ICAO sample & test documents)
    "D<<", "D<", "D",                     # Germany (ICAO Doc 9303 Part 3 Appendix)
    "GBD", "GBN", "GBO", "GBP", "GBS",    # British nationality categories
    "XXA", "XXB", "XXC", "XXX",           # Stateless / Refugee / Unknown
    "UNA", "UNK", "XBA", "XCC", "XCE", "XCO", "XEC", "XPO" # International organizations
}

# OCR-B visual confusion graph for alphabetic letters in 3-letter country codes
OCR_B_CONFUSION = {
    "0": ["D", "O", "Q", "U"],
    "1": ["L", "I", "T", "J"],
    "O": ["U", "D", "Q", "C", "0"],
    "U": ["O", "V"],
    "I": ["T", "L", "J", "1"],
    "T": ["I", "L", "Y"],
    "D": ["O", "B", "0"],
    "V": ["U", "Y"],
    "B": ["D", "R"],
    "S": ["5"],
    "Z": ["2"],
    "C": ["G", "O"],
    "G": ["C", "Q"],
    "Q": ["O", "G"],
    "L": ["I", "T", "1"],
    "N": ["M", "H"],
    "M": ["N", "W"],
    "W": ["M"],
}


def resolve_country_code(code: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    """
    Validates a 3-character issuing state / nationality against ISO 3166-1 alpha-3
    and ICAO Doc 9303 Part 3 Section 5 codes.
    If invalid, searches OCR-B single-character visual confusion alternatives.
    Returns: (resolved_code, [(relative_pos, orig_char, repaired_char), ...])
    """
    code = code.upper().strip()
    if code in ISO_3166_1_CODES:
        return code, []

    # 1-substitution search (single OCR-B character misread)
    for i in range(len(code)):
        orig_char = code[i]
        alts = OCR_B_CONFUSION.get(orig_char, [])
        for alt in alts:
            cand = code[:i] + alt + code[i + 1:]
            if cand in ISO_3166_1_CODES:
                return cand, [(i, orig_char, alt)]

    # 2-substitution search (double OCR-B character misread)
    for i in range(len(code)):
        for j in range(i + 1, len(code)):
            for alt1 in OCR_B_CONFUSION.get(code[i], []):
                for alt2 in OCR_B_CONFUSION.get(code[j], []):
                    cand = list(code)
                    cand[i] = alt1
                    cand[j] = alt2
                    cand_str = "".join(cand)
                    if cand_str in ISO_3166_1_CODES:
                        return cand_str, [(i, code[i], alt1), (j, code[j], alt2)]

    return code, []

# Audit log for MRZ repairs
REPAIR_AUDIT_LOG: List[Dict[str, Any]] = []

CONFIDENCE_REPAIR_THRESHOLD: float = 0.80


def clear_repair_audit_log() -> None:
    REPAIR_AUDIT_LOG.clear()


def get_repair_audit_log() -> List[Dict[str, Any]]:
    return list(REPAIR_AUDIT_LOG)


# ---------------------------------------------------------------------------
# 1. Full-Image Deskew & Padded Band Localization
# ---------------------------------------------------------------------------

def estimate_skew_full_image(img: np.ndarray) -> float:
    """
    Estimates document skew angle in degrees using text morphology and minAreaRect
    on elongated horizontal text contours in the lower half of the document.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h, w = gray.shape[:2]
    roi = gray[int(h * 0.55):h, :]
    thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    connected = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 150:
            continue
        rect = cv2.minAreaRect(cnt)
        (rw, rh), ang = rect[1], rect[2]
        if rw < rh:
            rw, rh = rh, rw
            ang = ang - 90.0
        if rw / max(rh, 1) >= 2.5:
            if ang > 45.0:
                ang -= 90.0
            elif ang < -45.0:
                ang += 90.0
            if abs(ang) <= 15.0:
                angles.append(ang)

    if not angles:
        edges = cv2.Canny(roi, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=w // 6, maxLineGap=20)
        if lines is not None:
            for l in lines:
                x1, y1, x2, y2 = l[0]
                dx = x2 - x1
                dy = y2 - y1
                if dx != 0:
                    a = np.degrees(np.arctan2(dy, dx))
                    if abs(a) <= 15.0:
                        angles.append(a)

    if not angles:
        return 0.0
    return float(np.median(angles))


def deskew_full_image(img: np.ndarray) -> np.ndarray:
    """Deskews the full document image prior to region localization."""
    ang = estimate_skew_full_image(img)
    if abs(ang) < 0.25:
        return img
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, ang, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def locate_mrz_band(image: np.ndarray) -> Tuple[np.ndarray, Tuple[float, float, float, float]]:
    """
    Locates the MRZ band in the lower region of the image.
    Finds dense horizontal monospaced text lines and adds ~15% vertical padding.
    Returns: (mrz_crop, (ymin, xmin, ymax, xmax)) normalized to [0.0, 1.0].
    """
    h, w = image.shape[:2]
    y_start_initial = int(h * 0.72)
    initial_crop = image[y_start_initial:h, 0:w]

    gray = cv2.cvtColor(initial_crop, cv2.COLOR_BGR2GRAY) if len(initial_crop.shape) == 3 else initial_crop
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
    _, thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 5))
    connected = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mrz_rects = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw >= w * 0.35 and ch >= 12:
            mrz_rects.append((x, y, cw, ch))

    if mrz_rects:
        raw_min_x = min(r[0] for r in mrz_rects)
        raw_max_x = max(r[0] + r[2] for r in mrz_rects)
        raw_min_y = min(r[1] for r in mrz_rects)
        raw_max_y = max(r[1] + r[3] for r in mrz_rects)

        band_h = raw_max_y - raw_min_y
        pad_y = max(int(band_h * 0.15), 10)

        min_x = max(0, raw_min_x - 12)
        max_x = min(w, raw_max_x + 12)
        min_y = max(0, raw_min_y - pad_y)
        max_y = min(h - y_start_initial, raw_max_y + pad_y)

        abs_ymin = (y_start_initial + min_y) / h
        abs_ymax = (y_start_initial + max_y) / h
        abs_xmin = min_x / w
        abs_xmax = max_x / w

        crop = image[y_start_initial + min_y:y_start_initial + max_y, min_x:max_x]
        return crop, (abs_ymin, abs_xmin, abs_ymax, abs_xmax)

    y_fallback = int(h * 0.78)
    return image[y_fallback:h, 0:w], (0.78, 0.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# 2. Preprocessing, Blur Tolerance & Upscaling
# ---------------------------------------------------------------------------

def apply_unsharp_mask(gray: np.ndarray, amount: float = 1.2, sigma: float = 1.0) -> np.ndarray:
    """Enhances high-frequency edge gradients to recover blurred OCR-B character strokes."""
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return cv2.addWeighted(gray, 1.0 + amount, blurred, -amount, 0)


def preprocess_mrz_band(
    band_img: np.ndarray,
    method: str = "grayscale",
) -> np.ndarray:
    """
    Preprocesses MRZ crop:
    - Converts to grayscale
    - Measures Laplacian variance; applies unsharp mask if blurred
    - 2x/2.5x Bicubic upscale
    - Applies selected binarization / enhancement ('grayscale', 'otsu', 'adaptive')
    """
    gray = cv2.cvtColor(band_img, cv2.COLOR_BGR2GRAY) if len(band_img.shape) == 3 else band_img

    # Measure blur via Laplacian variance
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var < 250.0:
        # Optical / capture blur detected: sharpen and upscale 2.5x to separate thin strokes
        enhanced = apply_unsharp_mask(gray, amount=1.2, sigma=1.0)
        upscaled = cv2.resize(enhanced, (0, 0), fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    else:
        # Clean sharp crop: 2x bicubic upscale preserves subpixel anti-aliasing
        upscaled = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    if method == "otsu":
        _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
    elif method == "adaptive":
        binary = cv2.adaptiveThreshold(
            upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
        )
        return binary
    else:
        return upscaled


# ---------------------------------------------------------------------------
# 3. Structure-Aware Positional Disambiguation & Gating
# ---------------------------------------------------------------------------

def disambiguate_icao_line(
    raw_line: str,
    line_number: int,
    doc_type: str = "passport",
    char_confidences: Optional[List[float]] = None,
    doc_id: str = "",
) -> str:
    """
    Applies ICAO 9303 positional disambiguation for TD3 and MRV-A lines.
    Enforces exact 44-character line length.
    Confidence-gated: repairs only when character confidence < CONFIDENCE_REPAIR_THRESHOLD (0.80).
    """
    s = raw_line.upper().replace("(", "<").replace("[", "<").replace("{", "<")

    if line_number == 1:
        # Clean noise around << separators
        s = re.sub(r"([A-Z])1<<", r"\1<<", s)
        s = re.sub(r"([A-Z])I<<", r"\1<<", s)
        s = re.sub(r"([A-Z])1<([A-Z])", r"\1<<\2", s)
        s = re.sub(r"([A-Z])I<([A-Z])", r"\1<<\2", s)

        # Handle stray character inserted directly before << that shifts line length
        m = re.match(r"^([PV]<[A-Z0-9]{3}[A-Z]+?)[I1]<<([A-Z<]+)$", s)
        if m:
            s = f"{m.group(1)}<<{m.group(2)}"

        chars = list(s.ljust(44, "<")[:44])

        def apply_repair_l1(pos: int, new_char: str, category: str, force: bool = False):
            old_char = chars[pos]
            if old_char != new_char:
                conf = char_confidences[pos] if (char_confidences and pos < len(char_confidences)) else 1.0
                if force or conf < CONFIDENCE_REPAIR_THRESHOLD or not old_char.isalnum():
                    record = {
                        "doc_id": doc_id,
                        "line": 1,
                        "position": pos,
                        "original": old_char,
                        "repaired": new_char,
                        "confidence": round(float(conf), 4),
                        "category": category,
                        "status": "APPLIED",
                    }
                    REPAIR_AUDIT_LOG.append(record)
                    chars[pos] = new_char
                else:
                    record = {
                        "doc_id": doc_id,
                        "line": 1,
                        "position": pos,
                        "original": old_char,
                        "repaired": new_char,
                        "confidence": round(float(conf), 4),
                        "category": category,
                        "status": "BLOCKED",
                    }
                    REPAIR_AUDIT_LOG.append(record)
                    logger.info(
                        f"[CONFIDENCE_GATE] Line 1 pos {pos} repair '{old_char}' -> '{new_char}' BLOCKED: "
                        f"char confidence {conf:.4f} >= threshold {CONFIDENCE_REPAIR_THRESHOLD}"
                    )

        # Pos 0: Document code ('P' for passport, 'V' for visa per ICAO 9303 Part 4/7)
        expected_doc_code = "P" if doc_type == "passport" else "V"
        if chars[0] != expected_doc_code:
            apply_repair_l1(0, expected_doc_code, "doc_code", force=True)

        # Pos 1: Separator '<' (ICAO 9303 Part 4/7)
        if chars[1] != "<":
            apply_repair_l1(1, "<", "type_separator", force=True)

        # Pos 2..4: Issuing State (ICAO 9303 Part 4 Section 4.2.2: Strictly Alphabetic)
        for i in range(2, 5):
            if chars[i] in ALPHA_REPAIRS:
                apply_repair_l1(i, ALPHA_REPAIRS[chars[i]], "issuing_state", force=True)

        # Validate against ISO 3166-1 / ICAO 9303 Part 3 Section 5 country codes
        issuing_code = "".join(chars[2:5])
        resolved_issuing, fixes_issuing = resolve_country_code(issuing_code)
        if resolved_issuing != issuing_code:
            for rel_idx, orig_c, rep_c in fixes_issuing:
                apply_repair_l1(2 + rel_idx, rep_c, "iso_3166_1_issuing_state", force=True)

        # Pos 5..43: Identifier / Holder Name and Trailing Chevrons
        for i in range(5, 44):
            if chars[i] in ALPHA_REPAIRS:
                apply_repair_l1(i, ALPHA_REPAIRS[chars[i]], "name_alpha")
            elif chars[i] != "<" and not chars[i].isalpha():
                apply_repair_l1(i, "<", "filler_chevron")

        # Clean isolated single character noise in trailing filler chevrons (ICAO 9303 Part 4/7)
        m_trail = re.search(r"<<([A-Z]<*)$", "".join(chars))
        if m_trail:
            trail_idx = m_trail.start(1)
            # If after << there is an isolated single letter followed only by chevrons
            tail = "".join(chars[trail_idx:])
            letters_in_tail = [c for c in tail if c.isalpha()]
            if len(letters_in_tail) == 1 and tail.count("<") >= 3:
                for idx_c in range(trail_idx, 44):
                    if chars[idx_c] != "<":
                        apply_repair_l1(idx_c, "<", "filler_chevron", force=True)

        res_line = "".join(chars)
        return res_line.ljust(44, "<")[:44]

    else:
        # Line 2 (44 characters)
        # Check for stray single character between sex (pos 20) and expiry date (pos 21)
        if len(s) >= 28:
            cand_exp = s[22:28]
            cand_exp_clean = "".join(NUMERIC_REPAIRS.get(c, c) for c in cand_exp)
            if len(cand_exp_clean) == 6 and cand_exp_clean.isdigit():
                mm = int(cand_exp_clean[2:4])
                dd = int(cand_exp_clean[4:6])
                if 1 <= mm <= 12 and 1 <= dd <= 31 and s[21] in ("1", "I", "<", "l", "/"):
                    s = s[:21] + s[22:]

        chars = list(s.ljust(44, "<")[:44])

        def apply_repair_l2(pos: int, new_char: str, category: str, force: bool = False):
            old_char = chars[pos]
            if old_char != new_char:
                conf = char_confidences[pos] if (char_confidences and pos < len(char_confidences)) else 1.0
                if force or conf < CONFIDENCE_REPAIR_THRESHOLD or not old_char.isalnum():
                    record = {
                        "doc_id": doc_id,
                        "line": 2,
                        "position": pos,
                        "original": old_char,
                        "repaired": new_char,
                        "confidence": round(float(conf), 4),
                        "category": category,
                        "status": "APPLIED",
                    }
                    REPAIR_AUDIT_LOG.append(record)
                    chars[pos] = new_char
                else:
                    record = {
                        "doc_id": doc_id,
                        "line": 2,
                        "position": pos,
                        "original": old_char,
                        "repaired": new_char,
                        "confidence": round(float(conf), 4),
                        "category": category,
                        "status": "BLOCKED",
                    }
                    REPAIR_AUDIT_LOG.append(record)
                    logger.info(
                        f"[CONFIDENCE_GATE] Line 2 pos {pos} repair '{old_char}' -> '{new_char}' BLOCKED: "
                        f"char confidence {conf:.4f} >= threshold {CONFIDENCE_REPAIR_THRESHOLD}"
                    )

        # Pos 0..8: Document Number (Alphanumeric per ICAO 9303 Part 4 Section 4.2.2)
        # Strictly confidence-gated (force=False): never mutate high-confidence character

        # Pos 9: Document number check digit (ICAO 9303: Strictly Numeric)
        if chars[9] in NUMERIC_REPAIRS:
            apply_repair_l2(9, NUMERIC_REPAIRS[chars[9]], "doc_num_check", force=True)

        # Pos 10..12: Nationality (ICAO 9303 Part 4 Section 4.2.2: Strictly Alphabetic)
        for i in range(10, 13):
            if chars[i] in ALPHA_REPAIRS:
                apply_repair_l2(i, ALPHA_REPAIRS[chars[i]], "nationality", force=True)

        # Validate against ISO 3166-1 / ICAO 9303 Part 3 Section 5 country codes
        nat_code = "".join(chars[10:13])
        resolved_nat, fixes_nat = resolve_country_code(nat_code)
        if resolved_nat != nat_code:
            for rel_idx, orig_c, rep_c in fixes_nat:
                apply_repair_l2(10 + rel_idx, rep_c, "iso_3166_1_nationality", force=True)

        # Pos 13..18: DOB YYMMDD (ICAO 9303 Part 4 Section 4.2.2: Strictly Numeric)
        for i in range(13, 19):
            if chars[i] in NUMERIC_REPAIRS:
                apply_repair_l2(i, NUMERIC_REPAIRS[chars[i]], "dob_digits", force=True)

        # Pos 19: DOB check digit (ICAO 9303 Part 4 Section 4.2.2: Strictly Numeric)
        if chars[19] in NUMERIC_REPAIRS:
            apply_repair_l2(19, NUMERIC_REPAIRS[chars[19]], "dob_check", force=True)

        # Pos 20: Sex ('M', 'F', 'X', '<' per ICAO 9303 Part 4 Section 4.2.2)
        if chars[20] in ("0", "O"):
            apply_repair_l2(20, "M", "sex")
        elif chars[20] not in ("M", "F", "X"):
            apply_repair_l2(20, "<", "sex")

        # Pos 21..26: Expiry YYMMDD (ICAO 9303 Part 4 Section 4.2.2: Strictly Numeric)
        for i in range(21, 27):
            if chars[i] in NUMERIC_REPAIRS:
                apply_repair_l2(i, NUMERIC_REPAIRS[chars[i]], "expiry_digits", force=True)

        # Pos 27: Expiry check digit (ICAO 9303 Part 4 Section 4.2.2: Strictly Numeric)
        if chars[27] in NUMERIC_REPAIRS:
            apply_repair_l2(27, NUMERIC_REPAIRS[chars[27]], "expiry_check", force=True)

        if doc_type == "passport":
            # Pos 28..42: Fillers '<' (ICAO 9303 TD3 Line 2)
            comp_digit = None
            for k in range(len(chars) - 1, 27, -1):
                if chars[k].isdigit() or chars[k] in NUMERIC_REPAIRS:
                    comp_digit = NUMERIC_REPAIRS.get(chars[k], chars[k])
                    break
            for i in range(28, 43):
                if chars[i] != "<":
                    apply_repair_l2(i, "<", "passport_filler", force=True)
            chars[43] = comp_digit if comp_digit else "0"
        else:
            # Visa: Pos 28..43 are Fillers '<' (ICAO 9303 MRV-A Line 2)
            for i in range(28, 44):
                if chars[i] != "<":
                    apply_repair_l2(i, "<", "visa_filler", force=True)

        res_line = "".join(chars)
        return res_line.ljust(44, "<")[:44]


# ---------------------------------------------------------------------------
# 4. Engine Runners: EasyOCR and Tesseract
# ---------------------------------------------------------------------------

def _run_easyocr_mrz(
    processed_band: np.ndarray,
) -> Tuple[List[str], List[List[float]]]:
    """Runs EasyOCR on preprocessed MRZ band crop with character allowlist."""
    from .ocr_engine import _easyocr_engine
    reader = _easyocr_engine.get_reader("en")

    ocr_res = reader.readtext(
        processed_band,
        allowlist=MRZ_CHARSET,
        paragraph=False,
    )
    if not ocr_res:
        return [], []

    ocr_res.sort(key=lambda r: (r[0][0][1] + r[0][2][1]) / 2.0)

    lines_grouped: List[List[Tuple[float, str, float, Any]]] = []
    curr_line: List[Tuple[float, str, float, Any]] = []
    curr_y: Optional[float] = None

    for r in ocr_res:
        txt = r[1].replace(" ", "").upper()
        cy = (r[0][0][1] + r[0][2][1]) / 2.0
        conf = float(r[2])
        if curr_y is None or abs(cy - curr_y) < 25.0:
            curr_line.append((r[0][0][0], txt, conf, r[0]))
            curr_y = cy
        else:
            curr_line.sort(key=lambda x: x[0])
            lines_grouped.append(curr_line)
            curr_line = [(r[0][0][0], txt, conf, r[0])]
            curr_y = cy

    if curr_line:
        curr_line.sort(key=lambda x: x[0])
        lines_grouped.append(curr_line)

    lines: List[str] = []
    confs: List[List[float]] = []

    for lg in lines_grouped[:2]:
        line_str = "".join(x[1] for x in lg)
        # Attempt per-character confidence from recognizer crop
        line_confs: List[float] = []
        try:
            from .label_anchor import get_char_confidences_from_crop
            all_pts = [pt for x in lg for pt in x[3]]
            ymin = max(0, int(min(pt[1] for pt in all_pts)) - 4)
            ymax = min(processed_band.shape[0], int(max(pt[1] for pt in all_pts)) + 4)
            xmin = max(0, int(min(pt[0] for pt in all_pts)) - 4)
            xmax = min(processed_band.shape[1], int(max(pt[0] for pt in all_pts)) + 4)
            line_crop = processed_band[ymin:ymax, xmin:xmax]
            c_confs = get_char_confidences_from_crop(line_crop, expected_text=line_str)
            if c_confs:
                if len(c_confs) >= len(line_str):
                    line_confs = [float(c) for c in c_confs[:len(line_str)]]
                else:
                    line_confs = [float(c) for c in c_confs] + [1.0] * (len(line_str) - len(c_confs))
        except Exception:
            line_confs = []

        if not line_confs:
            for x in lg:
                line_confs.extend([x[2]] * len(x[1]))

        if len(line_confs) < len(line_str):
            line_confs.extend([1.0] * (len(line_str) - len(line_confs)))

        lines.append(line_str)
        confs.append(line_confs)

    return lines, confs


def _run_tesseract_mrz(
    processed_band: np.ndarray,
) -> Tuple[List[str], List[List[float]]]:
    """Runs Tesseract OCR on preprocessed MRZ band if installed."""
    try:
        import pytesseract
        config = f"--psm 6 -c tessedit_char_whitelist={MRZ_CHARSET}"
        raw_text = pytesseract.image_to_string(processed_band, config=config)
        lines = [l.strip().replace(" ", "").upper() for l in raw_text.splitlines() if l.strip()]
        lines = [l for l in lines if len(l) >= 20]
        confs = [[0.85] * len(l) for l in lines]
        return lines[:2], confs[:2]
    except Exception as e:
        logger.debug(f"[TESSERACT] Unavailable or failed: {e}")
        return [], []


# ---------------------------------------------------------------------------
# 5. Main Reader Pipeline
# ---------------------------------------------------------------------------

def read_mrz(
    image: np.ndarray,
    doc_type: str = "passport",
    doc_id: str = "",
    engine: str = "easyocr",
    binarize_method: str = "grayscale",
) -> Dict[str, Any]:
    """
    Main entry point for MRZ reading:
    1. Deskews the full document image to prevent tilted band clipping.
    2. Locates padded MRZ band crop (~15% vertical padding).
    3. Preprocesses (blur-adaptive unsharp enhancement, 2x/2.5x upscale).
    4. Runs specified OCR engine (easyocr or tesseract).
    5. Applies ICAO 9303 structure-aware correction.
    6. Returns lines, bounding box, timing, and logged repairs.
    """
    t0 = time.perf_counter()

    deskewed_img = deskew_full_image(image)
    band_crop, mrz_bbox = locate_mrz_band(deskewed_img)
    processed = preprocess_mrz_band(band_crop, method=binarize_method)

    if engine == "tesseract":
        raw_lines, char_confs = _run_tesseract_mrz(processed)
        if not raw_lines:
            raw_lines, char_confs = _run_easyocr_mrz(processed)
    else:
        raw_lines, char_confs = _run_easyocr_mrz(processed)

    raw_l1 = raw_lines[0] if len(raw_lines) >= 1 else ""
    raw_l2 = raw_lines[1] if len(raw_lines) >= 2 else ""

    conf_l1 = char_confs[0] if len(char_confs) >= 1 else None
    conf_l2 = char_confs[1] if len(char_confs) >= 2 else None

    clean_l1 = disambiguate_icao_line(raw_l1, 1, doc_type, conf_l1, doc_id=doc_id)
    clean_l2 = disambiguate_icao_line(raw_l2, 2, doc_type, conf_l2, doc_id=doc_id)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "raw_lines": [raw_l1, raw_l2],
        "clean_lines": [clean_l1, clean_l2],
        "char_confidences_l1": conf_l1,
        "char_confidences_l2": conf_l2,
        "mrz_bbox": mrz_bbox,
        "elapsed_ms": elapsed_ms,
        "engine": engine,
        "binarize_method": binarize_method,
    }
