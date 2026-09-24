"""
label_anchor.py - Layout-Independent Label-Anchored Field Extraction.

Replaces rigid coordinate templates with 2D spatial proximity and label anchoring:
1. Multilingual Label Dictionaries (English, Hindi, Tamil, French).
2. Comprehensive Anti-Label Blocklist (ensures bilingual labels are never returned as values).
3. 2D Spatial Proximity Search (right-box or below-box based on layout characteristics).
4. Multi-Number Disambiguation (e.g. Visa number vs Passport number on visa cards).
5. Multi-Line Field Accumulation (e.g. multi-line Address blocks).
6. Cascade: label_anchor -> pattern_fallback -> coordinate_template.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Bounding box format: (ymin, xmin, ymax, xmax) normalized to [0.0, 1.0]
RegionBBox = Tuple[float, float, float, float]


@dataclass
class OCRBox:
    """Represents an OCR-detected text box with coordinates and confidence."""
    text: str
    confidence: float
    bbox: RegionBBox  # (ymin, xmin, ymax, xmax) normalized [0.0, 1.0]
    char_confidences: Optional[List[float]] = None

    @property
    def ymin(self) -> float:
        return self.bbox[0]

    @property
    def xmin(self) -> float:
        return self.bbox[1]

    @property
    def ymax(self) -> float:
        return self.bbox[2]

    @property
    def xmax(self) -> float:
        return self.bbox[3]

    @property
    def cx(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def h(self) -> float:
        return max(0.001, self.bbox[2] - self.bbox[0])

    @property
    def w(self) -> float:
        return max(0.001, self.bbox[3] - self.bbox[1])

    def clean_text(self) -> str:
        return self.text.strip()


# ---------------------------------------------------------------------------
# Multilingual Anti-Label Blocklist (English, Hindi, Tamil, French)
# Note: Values such as MALE, FEMALE, UTO, INDIA are EXCLUDED so they are never blocklisted.
# ---------------------------------------------------------------------------

_LABEL_BLOCKLIST_WORDS: Set[str] = {
    # English Labels & corrupted OCR readings
    "SURNAME", "SURNAMES", "LAST", "NAME", "NAMES", "MAME", "FULL", "GIVEN", "FIRST", "FORENAMES",
    "HOLDER", "ELECTOR", "ELECTORS", "VOTER", "VOTERS", "ELECTOT", "FATHER", "FATHERS", "MOTHER", "MOTHERS",
    "HUSBAND", "HUSBANDS", "RELATION", "RELATIONS", "GUARDIAN", "GUARDIANS", "FALEI",
    "DOB", "DATE", "BIRTH", "YEAR", "YOB", "SEX", "GENDER",
    "NATIONALITY", "NATION", "CITIZENSHIP", "PLACE", "ISSUE", "ISSUED",
    "PASSPORT", "VISA", "DOCUMENT", "NUMBER", "NO", "NUM", "FOLIO", "TYPE", "CATEGORY",
    "ENTRIES", "ENTRY", "VALID", "EXPIRY", "EXPIRATION", "UNTIL", "TILL", "FROM",
    "PERMANENT", "ACCOUNT", "PAN", "INCOME", "TAX", "DEPARTMENT", "GOVT", "GOVERNMENT",
    "AADHAAR", "UIDAI", "UID", "ENROLMENT", "MERI", "PEHCHAN", "MERA",
    "EPIC", "ELECTION", "COMMISSION", "PHOTO", "IDENTITY", "CARD", "ELECTORAL", "OFFICER",
    "ADDRESS", "RESIDENTIAL", "SIGNATURE", "SIGN",
    "SPECIMEN", "SAMPLE", "TEST", "SYNTHETIC", "FICTIONAL", "CLEARANCE",
    # French Labels & corrupted OCR readings
    "NOM", "NOMS", "NONI", "PRENOM", "PRENOMS", "PRÉNOM", "PRÉNOMS", "COMPLET",
    "NAISSANCE", "NATIONALITE", "NATIONALITÉ", "SEXE", "PASSEPORT",
    "DU", "DE", "DEXPIRATION", "EXPIRATION", "VALABLE", "AU", "CATEGORIE", "CATÉGORIE",
    "ENTREE", "ENTREES", "ENTRÉE", "ENTRÉES", "LIEU", "AUTORITE", "AUTORITÉ",
    # Hindi Labels (romanized & Devanagari)
    "नाम", "उपनाम", "पूरा", "पिता", "माता", "पति", "संबंधी", "का", "के", "की",
    "जन्म", "तिथि", "तारीख", "वर्ष", "लिंग",
    "राष्ट्रीयता", "पहचान", "पत्र", "संख्या", "निर्वाचन", "आयोग",
    "आयकर", "विभाग", "स्थायी", "खाता", "आधार", "पता", "निवासी",
    # Tamil Labels
    "பெயர்", "தந்தை", "பிறந்த", "தேதி", "பாலினம்", "முகவரி", "அடையாள", "அட்டை", "எண்",
    # Corrupted OCR variations on scanned cards
    "SUMAME", "BUMAME", "SURAME", "SUMAN", "SUMNAME", "GRENINES", "CHENIUT", "FUT", "EAI", "MRTHKE",
    "ST4N", "8EX", "BEX", "524", "SE]", "DALETA", "EAN", "NON", "OOTN", "PENON", "FENON", "GENTNT",
    "NIMT", "MAMT", "FUTTE", "DLU", "DRE", "DETTH", "PSTM5S", "IANTE", "ELCLON", "FLT"
}

_LABEL_BLOCKLIST_EXACT: Set[str] = {
    # Full phrases
    "SURNAME / NOM", "GIVEN NAMES / PRENOMS", "GIVEN NAMES / PRÉNOMS", "GIVEN NAMES",
    "NATIONALITY / NATIONALITÉ", "NATIONALITY / NATIONALITE",
    "DATE OF BIRTH / DATE DE NAISSANCE", "DATE OF BIRTH", "DATE DE NAISSANCE",
    "SEX / SEXE", "DATE OF EXPIRY / DATE D'EXPIRATION", "DATE OF EXPIRY", "DATE D'EXPIRATION",
    "PASSPORT NO / NO DU PASSEPORT", "PASSPORT NO. / NO. DU PASSEPORT", "NO DU PASSEPORT", "NO. DU PASSEPORT",
    "VISA NUMBER / NO. DU VISA", "VISA NUMBER / NO_DU VISA", "VISA NUMBER", "NO DU VISA", "NO. DU VISA", "DU VISA",
    "NAME / NOM", "PASSPORT NO / PASSEPORT", "PASSPORT NO. / PASSEPORT", "PASSEPORT",
    "VALID FROM / DU", "VALID FROM", "VALABLE DU", "EXPIRY / UNTIL", "EXPIRY", "UNTIL", "VALABLE AU",
    "TYPE / CATEGORIE", "TYPE / CATÉGORIE", "ENTRIES / ENTREES", "ENTRIES / ENTRÉES",
    "INCOME TAX DEPARTMENT", "GOVT OF INDIA", "GOVT. OF INDIA", "GOVERNMENT OF INDIA",
    "PERMANENT ACCOUNT NUMBER", "PERMANENT ACCOUNT NUMBER CARD", "PAN",
    "ELECTION COMMISSION OF INDIA", "ELECTOR PHOTO IDENTITY CARD",
    "UNIQUE IDENTIFICATION AUTHORITY OF INDIA", "MERA AADHAAR MERI PEHCHAN",
    "CHIEF ELECTORAL OFFICER", "SPECIMEN", "FICTIONAL TEST DOCUMENT", "SYNTHETIC SPECIMEN",
    "FATHER'S NAME", "FATHER S NAME", "FATHER S MAME", "FATHER'S MAME", "ELECTOR'S NAME", "ELECTOR S NAME",
    "ELECTOR'S MAME", "ELECTOR S MAME", "S MAME", "'S MAME", "'S | AME", "'$ MAME",
    "ELECTOT? FO", "? FO", "FO", "FATHER'S | AME;", "FATHER'S | AME", "| AME;", "| AME", "S | AME"
}


def is_blocklisted_label(val: str) -> bool:
    """
    Returns True if the string is merely a label header or prompt phrase
    in English, French, Hindi, or Tamil, and must not be treated as a user value.
    """
    if not val:
        return True
    s = val.strip().upper()
    if s in ("M", "F", "X", "MALE", "FEMALE", "UTO", "INDIA", "INDIAN"):
        return False

    s_clean = re.sub(r"[:/\-.,;()|'$]+", " ", s).strip()
    if s in _LABEL_BLOCKLIST_EXACT or s_clean in _LABEL_BLOCKLIST_EXACT:
        return True

    words = s_clean.split()
    if not words:
        return True

    # Check if all words belong to the label blocklist
    if all(w in _LABEL_BLOCKLIST_WORDS for w in words):
        return True

    # Filter out label fragments ending with colon or punctuation
    if len(words) <= 2 and any(w in _LABEL_BLOCKLIST_WORDS for w in words) and (val.endswith(":") or val.endswith(";") or val.endswith("-")):
        return True

    # Common compound noise like "VISA NUMBER / NO_DU VISA:"
    if "VISA" in words and any(w in ("NO", "NUM", "NUMBER", "DU") for w in words):
        return True
    if any("PASSPORT" in w or "PASSEPORT" in w for w in words):
        if any(w in ("NO", "NUM", "NUMBER", "DU", "INO", "MO") for w in words):
            return True
    if any(w in ("EXPIRY", "EXPIRATION", "VALABLE") for w in words) and any(w in ("DATE", "UNTIL", "AU", "DU") for w in words):
        return True
    if any(w in ("BIRTH", "NAISSANCE") for w in words) and any(w in ("DATE", "OF", "DE", "DOB") for w in words):
        return True

    return False


CONFIDENCE_REPAIR_THRESHOLD: float = 0.80

REPAIR_AUDIT_LOG: List[Dict[str, Any]] = []


def log_repair(field: str, original: str, repaired: str, confidence: float, reason: str) -> None:
    record = {
        "field": field,
        "original": original,
        "repaired": repaired,
        "confidence": round(float(confidence), 4),
        "reason": reason,
    }
    REPAIR_AUDIT_LOG.append(record)
    logger.info(f"[OCR REPAIR] Field '{field}': '{original}' -> '{repaired}' (conf={confidence:.3f}, reason: {reason})")


def get_repair_audit_log() -> List[Dict[str, Any]]:
    return list(REPAIR_AUDIT_LOG)


def clear_repair_audit_log() -> None:
    REPAIR_AUDIT_LOG.clear()


def get_char_confidences_from_crop(crop_img: np.ndarray, expected_text: str = "") -> List[float]:
    """
    Extracts per-character confidence scores for a text crop using EasyOCR's recognizer.
    Falls back to single-character crops if recognizer is unavailable.
    """
    if crop_img is None or crop_img.size == 0:
        return []
    try:
        from .ocr_engine import _easyocr_engine
        reader = _easyocr_engine.get_reader("en")

        import cv2
        import torch
        import torch.nn.functional as F
        from easyocr.recognition import AlignCollate, ListDataset

        if len(crop_img.shape) == 3:
            img_gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        else:
            img_gray = crop_img

        imgH = 64
        AlignCollate_normal = AlignCollate(imgH=imgH, imgW=int(img_gray.shape[1] * (imgH / max(1, img_gray.shape[0]))), keep_ratio_with_pad=True)
        test_data = ListDataset([img_gray])
        test_loader = torch.utils.data.DataLoader(test_data, batch_size=1, shuffle=False, collate_fn=AlignCollate_normal)

        model = reader.recognizer
        converter = reader.converter
        device = reader.device
        model.eval()

        with torch.no_grad():
            for image_tensors in test_loader:
                image = image_tensors.to(device)
                batch_max_length = int(image.size(3) / 10)
                text_for_pred = torch.LongTensor(1, batch_max_length + 1).fill_(0).to(device)
                preds = model(image, text_for_pred)
                preds_prob = F.softmax(preds, dim=2).cpu().detach().numpy()
                values = preds_prob.max(axis=2)[0]
                indices = preds_prob.argmax(axis=2)[0]

                char_probs = []
                prev_idx = 0
                for idx, prob in zip(indices, values):
                    if idx != 0 and idx != prev_idx:
                        char_probs.append(float(prob))
                    prev_idx = idx

                if char_probs:
                    return char_probs
    except Exception as e:
        logger.debug(f"[CHAR_CONF] Recognizer failed: {e}")

    # Fallback to single-character crop OCR
    try:
        from .ocr_engine import _easyocr_engine
        reader = _easyocr_engine.get_reader("en")
        import cv2
        h, w = crop_img.shape[:2]
        n = max(1, len(expected_text)) if expected_text else 10
        char_w = w / n
        single_confs = []
        for i in range(n):
            x1 = max(0, int(i * char_w - char_w * 0.1))
            x2 = min(w, int((i + 1) * char_w + char_w * 0.1))
            c_crop = crop_img[:, x1:x2]
            if c_crop.shape[0] > 0 and c_crop.shape[1] > 0:
                c_lg = cv2.resize(c_crop, (0, 0), fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
                res = reader.readtext(c_lg, allowlist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                single_confs.append(float(res[0][2]) if res else 0.5)
            else:
                single_confs.append(0.5)
        return single_confs
    except Exception as e:
        logger.debug(f"[CHAR_CONF] Single crop fallback failed: {e}")
        return []


def clean_field_value(
    val: str,
    field_type: str = "text",
    confidence: float = 1.0,
    char_confidences: Optional[List[float]] = None,
) -> str:
    """
    Cleans up OCR artifacts, trailing labels, and colons.
    Slot-specific character repairs are strictly applied ONLY when raw OCR confidence
    is below CONFIDENCE_REPAIR_THRESHOLD (< 0.80) to avoid masking authentic tampering.
    When char_confidences are provided, gating is evaluated PER-CHARACTER for each ambiguous slot.
    A character at >= 0.80 (e.g. authentic 0.98) is NEVER repaired.
    All applied repairs are recorded in REPAIR_AUDIT_LOG.
    """
    if not val:
        return ""
    v = val.strip()
    v = re.sub(r"^[\s:/\-;,|.]+", "", v)
    v = re.sub(r"[\s:/\-;,|.]+$", "", v)

    if field_type == "date":
        norm_d = re.sub(r"[,.\-\s]", "/", v)
        norm_d = re.sub(r"\b(\d{2})(\d{2})[/](\d{4})\b", r"\1/\2/\3", norm_d)
        norm_d = re.sub(r"(\d{2}/\d{2})[27](\d{4})", r"\1/\2", norm_d)
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", norm_d)
        if m:
            return m.group(1)
        m2 = re.search(r"\b(\d{4}/\d{2}/\d{2})\b", norm_d)
        if m2:
            return m2.group(1)
        return ""

    elif field_type == "pan":
        clean_pan = re.sub(r"[^A-Z0-9]", "", v.upper())
        if len(clean_pan) == 10:
            p_prefix = clean_pan[:5]
            p_digits = clean_pan[5:9]
            p_suffix = clean_pan[9]
            if p_prefix.isalpha() and p_digits.isdigit() and p_suffix.isalpha():
                return clean_pan

            # Per-character gated repair:
            # An ambiguous slot is repaired ONLY if THAT character's confidence is < CONFIDENCE_REPAIR_THRESHOLD (0.80)
            DIGIT_SUBS = {"O": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
            SUFFIX_SUBS = {"0": "Q", "1": "I", "5": "S", "8": "B"}

            p_digits_rep = list(p_digits)
            for i, c in enumerate(p_digits):
                slot_idx = 5 + i
                if c in DIGIT_SUBS:
                    char_c = char_confidences[slot_idx] if (char_confidences and slot_idx < len(char_confidences)) else confidence
                    if char_c < CONFIDENCE_REPAIR_THRESHOLD:
                        p_digits_rep[i] = DIGIT_SUBS[c]
                        log_repair("pan_number", c, DIGIT_SUBS[c], char_c, f"Slot {slot_idx} digit repair (low char_conf={char_c:.4f})")
                    else:
                        logger.info(f"[GATING] Preserving slot {slot_idx} '{c}' (char_conf={char_c:.4f} >= {CONFIDENCE_REPAIR_THRESHOLD})")
            p_digits_rep = "".join(p_digits_rep)

            p_suffix_rep = p_suffix
            if p_suffix in SUFFIX_SUBS:
                suffix_slot_idx = 9
                char_c = char_confidences[suffix_slot_idx] if (char_confidences and suffix_slot_idx < len(char_confidences)) else confidence
                if char_c < CONFIDENCE_REPAIR_THRESHOLD:
                    p_suffix_rep = SUFFIX_SUBS[p_suffix]
                    log_repair("pan_number", p_suffix, SUFFIX_SUBS[p_suffix], char_c, f"Slot 9 suffix repair (low char_conf={char_c:.4f})")
                else:
                    logger.info(f"[GATING] Preserving slot 9 '{p_suffix}' (char_conf={char_c:.4f} >= {CONFIDENCE_REPAIR_THRESHOLD})")

            if p_prefix.isalpha() and p_digits_rep.isdigit() and p_suffix_rep.isalpha():
                return f"{p_prefix}{p_digits_rep}{p_suffix_rep}"

        m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", v.upper())
        if m:
            return m.group(1)
        return ""

    elif field_type == "aadhaar":
        digits = re.sub(r"[^\d]", "", v)
        if len(digits) == 12:
            return f"{digits[0:4]} {digits[4:8]} {digits[8:12]}"
        return ""

    elif field_type == "epic":
        clean_epic = re.sub(r"[^A-Z0-9]", "", v.upper())
        if len(clean_epic) == 10:
            if clean_epic[:3].isalpha() and clean_epic[3:].isdigit():
                return clean_epic
            # Apply repair ONLY when raw OCR confidence is low
            if confidence < CONFIDENCE_REPAIR_THRESHOLD:
                p3 = clean_epic[:3].replace("0", "O").replace("1", "I")
                d7 = (
                    clean_epic[3:]
                    .replace("O", "0")
                    .replace("I", "1")
                    .replace("Z", "2")
                    .replace("S", "5")
                    .replace("G", "6")
                    .replace("B", "8")
                )
                if p3.isalpha() and d7.isdigit():
                    repaired_epic = f"{p3}{d7}"
                    if repaired_epic != clean_epic:
                        log_repair("epic_number", clean_epic, repaired_epic, confidence, "Slot-specific prefix/digit repair (low confidence)")
                    return repaired_epic
        m = re.search(r"\b([A-Z]{3}[0-9]{7})\b", v.upper())
        if m:
            return m.group(1)
        return ""

    elif field_type == "passport_number":
        clean_p = re.sub(r"[^A-Z0-9]", "", v.upper())
        if 8 <= len(clean_p) <= 9:
            if clean_p[0].isalpha() and clean_p[1:].isdigit():
                return clean_p
            if confidence < CONFIDENCE_REPAIR_THRESHOLD:
                prefix = clean_p[0].replace("0", "U").replace("1", "I")
                digits = clean_p[1:].replace("O", "0").replace("I", "1")
                if prefix.isalpha() and digits.isdigit():
                    repaired_p = f"{prefix}{digits}"
                    if repaired_p != clean_p:
                        log_repair("passport_number", clean_p, repaired_p, confidence, "Passport prefix/digit repair (low confidence)")
                    return repaired_p
        m = re.search(r"\b([A-Z][0-9]{7,8})\b", v.upper())
        if m:
            return m.group(1)
        return ""

    elif field_type == "visa_number":
        clean_v = re.sub(r"[^A-Z0-9]", "", v.upper())
        if 8 <= len(clean_v) <= 10:
            if clean_v[0] == "V" and clean_v[1:].isdigit():
                return clean_v
            if confidence < CONFIDENCE_REPAIR_THRESHOLD:
                prefix = "V" if clean_v[0] in ("V", "U") else clean_v[0]
                digits = clean_v[1:].replace("O", "0").replace("I", "1")
                if prefix == "V" and digits.isdigit():
                    repaired_v = f"{prefix}{digits}"
                    if repaired_v != clean_v:
                        log_repair("visa_number", clean_v, repaired_v, confidence, "Visa prefix/digit repair (low confidence)")
                    return repaired_v
        m = re.search(r"\b(V[0-9]{7,9})\b", v.upper())
        if m:
            return m.group(1)
        return ""

    elif field_type == "sex":
        v_upper = v.upper().strip()
        if v_upper in ("M", "F", "X"):
            return v_upper
        if "FEMALE" in v_upper or "/F" in v_upper:
            return "F"
        if "MALE" in v_upper or "/M" in v_upper:
            return "M"
        if confidence < CONFIDENCE_REPAIR_THRESHOLD:
            if v_upper in ("0", "O"):
                log_repair("sex", v_upper, "M", confidence, "Sex 0/O -> M repair (low confidence)")
                return "M"
        m = re.search(r"\b([MFX])\b", v_upper)
        if m:
            return m.group(1)
        return ""

    elif field_type == "gender":
        v_upper = v.upper().strip()
        if "FEMALE" in v_upper or v_upper == "F":
            return "Female"
        if "MALE" in v_upper or v_upper == "M":
            return "Male"
        if "TRANSGENDER" in v_upper or v_upper == "X":
            return "Transgender"
        return ""

    elif field_type == "nationality":
        v_upper = v.upper().replace(".", "").strip()
        if v_upper in ("UTO", "IND", "USA", "GBR", "FRA", "DEU", "CAN", "AUS"):
            return v_upper
        if "UTO" in v_upper:
            return "UTO"
        if "INDIAN" in v_upper:
            return "INDIAN"
        return ""

    # Default text cleanup (NO hardcoded name rules)
    v = re.sub(r"\s+", " ", v).strip(" ,:;/-|'\"$")
    return v


# ---------------------------------------------------------------------------
# Multilingual Label Synonyms Dictionary
# ---------------------------------------------------------------------------

FIELD_LABEL_SYNONYMS: Dict[str, List[str]] = {
    "name": [
        "NAME", "FULL NAME", "NOM", "NOM COMPLET", "ELECTOR'S NAME", "ELECTOR NAME",
        "ELECTOT", "VOTER NAME", "HOLDER'S NAME", "HOLDER NAME", "RESIDENT NAME",
        "नाम", "पूरा नाम", "मतदाता का नाम", "பெயர்"
    ],
    "surname": [
        "SURNAME", "NOM", "SURNAME / NOM", "LAST NAME", "SURNAMES", "उपनाम"
    ],
    "given_names": [
        "GIVEN NAMES", "GIVEN NAMES / PRENOMS", "GIVEN NAMES / PRÉNOMS", "PRENOMS",
        "PRÉNOMS", "GIVEN NAME", "FIRST NAME", "FORENAMES"
    ],
    "father_name": [
        "FATHER'S NAME", "FATHERS NAME", "FATHER NAME", "FALEI", "RELATION'S NAME", "HUSBAND'S NAME",
        "FATHER", "पिता का नाम", "पिता / पति का नाम", "தந்தை பெயர்"
    ],
    "date_of_birth": [
        "DATE OF BIRTH", "DATE OF BIRTH / DATE DE NAISSANCE", "DOB", "DATE DE NAISSANCE",
        "BIRTH DATE", "D.O.B", "DATE OF BLRTH", "DOB:", "जन्म तिथि", "जन्म तारीख", "பிறந்த தேதி"
    ],
    "gender": [
        "GENDER", "SEX", "SEX / SEXE", "SEXE", "लिंग", "பாலினம்"
    ],
    "sex": [
        "SEX", "SEX / SEXE", "SEXE", "GENDER", "लिंग", "பாலினம்"
    ],
    "nationality": [
        "NATIONALITY", "NATIONALITY / NATIONALITÉ", "NATIONALITY / NATIONALITE",
        "NATIONALITÉ", "NATIONALITE", "NATION", "CITIZENSHIP", "राष्ट्रीयता"
    ],
    "pan_number": [
        "PERMANENT ACCOUNT NUMBER", "PERMANENT ACCOUNT NUMBER CARD", "PAN",
        "PAN NO", "PAN NUMBER", "ACCOUNT NO", "स्थायी खाता संख्या"
    ],
    "aadhaar_number": [
        "AADHAAR", "AADHAAR NO", "AADHAAR NUMBER", "UID", "UIDAI", "आधार", "आधार संख्या"
    ],
    "epic_number": [
        "EPIC NO", "EPIC NUMBER", "IDENTITY CARD NO", "ELECTOR PHOTO IDENTITY CARD",
        "EPIC", "CARD NO", "पहचान पत्र संख्या"
    ],
    "passport_number": [
        "PASSPORT NO", "PASSPORT NO.", "PASSPORT NO. / NO. DU PASSEPORT", "PASSPORT NUMBER",
        "NO. DU PASSEPORT", "NO DU PASSEPORT", "PASSEPORT", "DOCUMENT NO", "DOCUMENT NUMBER"
    ],
    "visa_number": [
        "VISA NUMBER / NO. DU VISA", "VISA NUMBER / NO_DU VISA", "VISA NUMBER",
        "VISA NO", "VISA NO.", "NO DU VISA", "NO. DU VISA", "FOLIO NO"
    ],
    "valid_from": [
        "VALID FROM / DU", "VALID FROM", "VALABLE DU", "ENTRY FROM", "EFFECTIVE DATE"
    ],
    "date_of_expiry": [
        "DATE OF EXPIRY / DATE D'EXPIRATION", "DATE OF EXPIRY", "EXPIRY / UNTIL",
        "EXPIRY", "EXPIRY DATE", "VALID UNTIL", "VALABLE AU", "DATE D'EXPIRATION", "EXPIRATION"
    ],
    "address": [
        "ADDRESS", "AADRESS", "PERMANENT ADDRESS", "RESIDENTIAL ADDRESS", "पता", "निवासी", "முகவரி"
    ],
}


# ---------------------------------------------------------------------------
# Core Spatial Proximity Algorithms
# ---------------------------------------------------------------------------

def find_label_box(boxes: List[OCRBox], label_synonyms: List[str]) -> Optional[Tuple[OCRBox, str]]:
    best_box = None
    best_syn = None
    best_score = -1

    for syn in label_synonyms:
        syn_upper = syn.upper().strip()
        syn_tokens = set(syn_upper.split())
        for box in boxes:
            txt_upper = box.text.upper().strip()
            # 1. Exact or prefix match
            if txt_upper == syn_upper or txt_upper.startswith(syn_upper + ":") or txt_upper.startswith(syn_upper + ";") or txt_upper.startswith(syn_upper + " "):
                return box, syn

            # 2. Word boundary match
            if len(syn_upper) <= 5:
                # Never match short tokens (NOM, NAME, SEX, PAN) as substring without word boundaries
                if re.search(rf"\b{re.escape(syn_upper)}\b", txt_upper):
                    score = len(syn_upper) / max(1, len(txt_upper))
                    if score > best_score:
                        best_score = score
                        best_box = box
                        best_syn = syn
            else:
                if syn_upper in txt_upper:
                    score = len(syn_upper) / max(1, len(txt_upper))
                    if score > best_score:
                        best_score = score
                        best_box = box
                        best_syn = syn

            # 3. Token subset match
            box_tokens = set(re.sub(r"[:/\-.,;()|]+", " ", txt_upper).split())
            if syn_tokens.issubset(box_tokens) and len(syn_tokens) > 1:
                score = len(syn_tokens) / max(1, len(box_tokens))
                if score > best_score:
                    best_score = score
                    best_box = box
                    best_syn = syn

    if best_box is not None:
        return best_box, best_syn
    return None


def find_value_in_same_box(label_box: OCRBox, label_str: str, field_type: str = "text") -> Optional[str]:
    txt = label_box.text.strip()
    cleaned_label = re.sub(r"[:/\-.,;()|]+", " ", label_str).strip()

    # 1. Direct regex after label
    m = re.search(rf"\b{re.escape(label_str)}\b\s*[:/\-;]?\s*(.+)", txt, re.IGNORECASE)
    if not m and cleaned_label:
        m = re.search(rf"(?:{re.escape(cleaned_label)})\s*[:/\-;]?\s*(.+)", txt, re.IGNORECASE)

    if m:
        candidate = m.group(1).strip()
        cand_letters = re.sub(r"[^A-Za-z0-9]", "", candidate)
        if candidate and cand_letters and (field_type in ("gender", "sex") or not is_blocklisted_label(candidate)):
            if field_type == "text" and (len(cand_letters) <= 2 or is_blocklisted_label(cand_letters)):
                pass
            elif field_type == "pan" and not (len(cand_letters) == 10 and cand_letters[:5].isalpha()):
                pass
            else:
                cleaned = clean_field_value(candidate, field_type, confidence=label_box.confidence)
                if cleaned:
                    return cleaned

    # 2. Split on common delimiters (:, ;, -)
    for delim in (":", ";", "-"):
        if delim in txt:
            parts = txt.split(delim, 1)
            right = parts[1].strip()
            right_letters = re.sub(r"[^A-Za-z0-9]", "", right)
            if right and right_letters and (field_type in ("gender", "sex") or not is_blocklisted_label(right)):
                if field_type == "text" and (len(right_letters) <= 2 or is_blocklisted_label(right_letters)):
                    pass
                elif field_type == "pan" and not (len(right_letters) == 10 and right_letters[:5].isalpha()):
                    pass
                else:
                    cleaned = clean_field_value(right, field_type, confidence=label_box.confidence)
                    if cleaned:
                        return cleaned

    # 3. For structured fields (EPIC, PAN, Aadhaar, dates), check if pattern is inside box
    if field_type == "epic":
        m = re.search(r"\b([A-Z]{3}[0-9]{7})\b", txt.upper())
        if m:
            return m.group(1)
    elif field_type == "pan":
        m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", txt.upper())
        if m:
            return m.group(1)
    elif field_type == "date":
        m = re.search(r"\b(\d{2}[/,.\-]?\d{2}[/,.\-]\d{4})\b", txt)
        if m:
            return clean_field_value(m.group(1), "date", confidence=label_box.confidence)
    elif field_type in ("gender", "sex"):
        cleaned = clean_field_value(txt, field_type, confidence=label_box.confidence)
        if cleaned:
            return cleaned

    return None


def find_right_neighbor_box(
    label_box: OCRBox,
    boxes: List[OCRBox],
    max_dx: float = 0.65,
    max_dy: float = 0.08,
    field_type: str = "text",
) -> Optional[OCRBox]:
    candidates = []
    for b in boxes:
        if b is label_box:
            continue
        # Right neighbor MUST start to the right of label_box
        dx = b.xmin - label_box.xmax
        if dx < -0.02 or dx > max_dx:
            continue
        if b.xmin < label_box.xmin + 0.02:
            continue

        v_overlap = min(b.ymax, label_box.ymax) - max(b.ymin, label_box.ymin)
        dy = abs(b.cy - label_box.cy)
        max_allowed_dy = max(max_dy, 0.8 * max(label_box.h, b.h))
        if v_overlap <= 0 and dy > max_allowed_dy:
            continue

        if field_type in ("gender", "sex"):
            cleaned = clean_field_value(b.text, field_type, confidence=b.confidence)
            if cleaned:
                candidates.append((dy * 2.0 + max(0.0, dx), b))
        elif not is_blocklisted_label(b.text):
            if field_type == "text":
                c_text = b.clean_text()
                if len(c_text) <= 2:
                    continue
                # Exclude PAN/EPIC numbers from text
                if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", c_text):
                    continue
                if re.match(r"^[A-Z]{3}[0-9]{7}$", c_text):
                    continue
            candidates.append((dy * 2.0 + max(0.0, dx), b))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def find_below_neighbor_box(
    label_box: OCRBox,
    boxes: List[OCRBox],
    max_dy: float = 0.22,
    max_dx: float = 0.45,
    field_type: str = "text",
) -> Optional[OCRBox]:
    candidates = []
    for b in boxes:
        if b is label_box:
            continue
        # Below neighbor MUST be vertically below label_box
        if b.cy <= label_box.cy + 0.012:
            continue

        dy = b.ymin - label_box.ymax
        h_overlap = min(b.xmax, label_box.xmax) - max(b.xmin, label_box.xmin)
        high_h_overlap = (h_overlap > 0.15 * min(label_box.w, b.w)) or (abs(b.xmin - label_box.xmin) <= 0.18)
        allowed_min_dy = -0.03 if high_h_overlap else -0.01
        allowed_max_dy = (max_dy * 1.5) if high_h_overlap else max_dy

        if allowed_min_dy <= dy <= allowed_max_dy:
            dx = abs(b.cx - label_box.cx)
            if high_h_overlap or dx <= max_dx or abs(b.xmin - label_box.xmin) <= 0.30:
                if field_type in ("gender", "sex"):
                    cleaned = clean_field_value(b.text, field_type, confidence=b.confidence)
                    if cleaned:
                        dist = dy + 0.4 * abs(b.xmin - label_box.xmin)
                        candidates.append((dist, b))
                elif not is_blocklisted_label(b.text):
                    if field_type == "text":
                        c_text = b.clean_text()
                        if len(c_text) <= 2:
                            continue
                        if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", c_text):
                            continue
                        if re.match(r"^[A-Z]{3}[0-9]{7}$", c_text):
                            continue
                    dist = dy + 0.4 * abs(b.xmin - label_box.xmin)
                    candidates.append((dist, b))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def accumulate_address_boxes_below(
    label_box: OCRBox,
    boxes: List[OCRBox],
    max_y_limit: float = 0.85,
) -> Tuple[str, float]:
    addr_parts = []
    conf_sum = 0.0
    count = 0

    same_box_val = find_value_in_same_box(label_box, "Address", "text")
    if not same_box_val:
        same_box_val = find_value_in_same_box(label_box, "Aadress", "text")
    if same_box_val:
        clean_lead = re.sub(r"^(?:Address|Aadress|47)\s*[:\-]?\s*", "", same_box_val, flags=re.I)
        addr_parts.append(clean_lead)
        conf_sum += label_box.confidence
        count += 1

    below_boxes = [
        b for b in boxes
        if b is not label_box and b.ymin >= label_box.ymin and b.ymin <= max_y_limit
    ]
    below_boxes.sort(key=lambda b: (b.ymin, b.xmin))

    for b in below_boxes:
        txt = b.clean_text()
        txt_u = txt.upper()
        if re.search(r"\b\d{4}\s+\d{4}\s+\d{4}\b", txt) or re.search(r"\b\d{12}\b", txt):
            break
        if "HELP@UIDAI" in txt_u or "WWW.UIDAI" in txt_u or "1947" in txt_u or "MERA AADHAAR" in txt_u:
            break
        if is_blocklisted_label(txt):
            continue
        if b.xmin <= 0.75:
            clean_b = re.sub(r"^(?:Address|Aadress|47)\s*[:\-]?\s*", "", txt, flags=re.I)
            addr_parts.append(clean_b)
            conf_sum += b.confidence
            count += 1

    full_addr = ", ".join(addr_parts) if addr_parts else ""
    full_addr = re.sub(r"\s+", " ", full_addr).strip(" ,-")
    avg_conf = (conf_sum / count) if count > 0 else 0.85
    return full_addr, round(avg_conf, 3)


# ---------------------------------------------------------------------------
# Multi-Number Disambiguation (Visa Number vs Passport Number)
# ---------------------------------------------------------------------------

def disambiguate_numbers_by_proximity(
    boxes: List[OCRBox],
    visa_label_box: Optional[OCRBox],
    passport_label_box: Optional[OCRBox],
) -> Tuple[Optional[Tuple[str, float]], Optional[Tuple[str, float]]]:
    visa_res = None
    passport_res = None

    candidates = []
    for b in boxes:
        txt = re.sub(r"[^A-Z0-9]", "", b.text.upper())
        if not is_blocklisted_label(b.text):
            if 7 <= len(txt) <= 12:
                candidates.append((b, txt))

    # 1. Visa Number candidate
    if visa_label_box:
        best_v = None
        min_dist = 999.0
        for b, txt in candidates:
            dist = np.hypot(b.cx - visa_label_box.cx, b.cy - visa_label_box.cy)
            if txt.startswith("V"):
                dist -= 0.25
            if dist < min_dist:
                min_dist = dist
                cleaned = clean_field_value(txt, "visa_number", confidence=b.confidence)
                if cleaned:
                    best_v = (cleaned, b.confidence)
        visa_res = best_v

    # 2. Passport Number candidate
    if passport_label_box:
        best_p = None
        min_dist = 999.0
        for b, txt in candidates:
            if visa_res and txt == visa_res[0]:
                continue
            dist = np.hypot(b.cx - passport_label_box.cx, b.cy - passport_label_box.cy)
            if dist < min_dist:
                min_dist = dist
                cleaned = clean_field_value(txt, "passport_number", confidence=b.confidence)
                if cleaned:
                    best_p = (cleaned, b.confidence)
        passport_res = best_p

    return visa_res, passport_res


# ---------------------------------------------------------------------------
# Document-Specific Label-Anchored Extractors
# ---------------------------------------------------------------------------

def extract_pan_anchored(
    boxes: List[OCRBox],
    full_text: str = "",
    image: Optional[np.ndarray] = None,
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    fields: Dict[str, Tuple[str, float]] = {}
    methods: Dict[str, str] = {}

    def _resolve_char_confs(b: OCRBox) -> Optional[List[float]]:
        if b.char_confidences is not None:
            return b.char_confidences
        if image is not None:
            h, w = image.shape[:2]
            y1, y2 = max(0, int(b.ymin * h)), min(h, int(b.ymax * h))
            x1, x2 = max(0, int(b.xmin * w)), min(w, int(b.xmax * w))
            if y2 > y1 and x2 > x1:
                b.char_confidences = get_char_confidences_from_crop(image[y1:y2, x1:x2], b.text)
                return b.char_confidences
        return None

    # 1. PAN Number
    pan_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["pan_number"])
    if pan_lbl_res:
        lbl_b, lbl_syn = pan_lbl_res
        same_pan = find_value_in_same_box(lbl_b, lbl_syn, "pan")
        if same_pan:
            fields["pan_number"] = (same_pan, lbl_b.confidence)
            methods["pan_number"] = "label_anchor"
        else:
            val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.22, field_type="pan") or find_right_neighbor_box(lbl_b, boxes, field_type="pan")
            if val_b:
                c_confs = _resolve_char_confs(val_b)
                pan_val = clean_field_value(val_b.text, "pan", confidence=val_b.confidence, char_confidences=c_confs)
                if pan_val and len(pan_val) == 10:
                    fields["pan_number"] = (pan_val, val_b.confidence)
                    methods["pan_number"] = "label_anchor"

    if "pan_number" not in fields:
        for b in boxes:
            if 0.18 <= b.ymin <= 0.32 and 0.03 <= b.xmin <= 0.35:
                c_confs = _resolve_char_confs(b)
                pan_cand = clean_field_value(b.text, "pan", confidence=b.confidence, char_confidences=c_confs)
                if pan_cand and len(pan_cand) == 10:
                    fields["pan_number"] = (pan_cand, b.confidence)
                    methods["pan_number"] = "pattern_fallback"
                    break

    if "pan_number" not in fields:
        for b in boxes:
            c_confs = _resolve_char_confs(b)
            pan_cand = clean_field_value(b.text, "pan", confidence=b.confidence, char_confidences=c_confs)
            if pan_cand and len(pan_cand) == 10:
                fields["pan_number"] = (pan_cand, b.confidence)
                methods["pan_number"] = "pattern_fallback"
                break

    if "pan_number" not in fields:
        m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", full_text.upper())
        if m:
            fields["pan_number"] = (m.group(1), 0.90)
            methods["pan_number"] = "pattern_fallback"

    # 2. Name
    name_lbl_res = None
    for cand_syn in ["Name:", "Name", "NAME", "नाम", "Mame:", "Mame"]:
        res = find_label_box(boxes, [cand_syn])
        if res and "FATHER" not in res[0].text.upper() and "ACCOUNT" not in res[0].text.upper():
            name_lbl_res = res
            break

    if name_lbl_res:
        lbl_b, _ = name_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.08)
        if val_b:
            name_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if name_val and not is_blocklisted_label(name_val) and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", name_val):
                fields["name"] = (name_val, val_b.confidence)
                methods["name"] = "label_anchor"

    if "name" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.28 <= b.ymin <= 0.40 and 0.18 <= b.xmin <= 0.65:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", t):
                        fields["name"] = (t, b.confidence)
                        methods["name"] = "pattern_fallback"
                        break

    # 3. Father's Name
    fn_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["father_name"])
    if fn_lbl_res:
        lbl_b, _ = fn_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.08)
        if val_b:
            fn_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if fn_val and not is_blocklisted_label(fn_val) and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", fn_val):
                fields["father_name"] = (fn_val, val_b.confidence)
                methods["father_name"] = "label_anchor"

    if "father_name" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.45 <= b.ymin <= 0.58 and 0.18 <= b.xmin <= 0.65:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", t) and t != fields.get("name", ("", 0))[0]:
                        fields["father_name"] = (t, b.confidence)
                        methods["father_name"] = "pattern_fallback"
                        break

    # 4. Date of Birth
    dob_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["date_of_birth"])
    if dob_lbl_res:
        lbl_b, _ = dob_lbl_res
        same_dob = find_value_in_same_box(lbl_b, "Date of Birth", "date") or find_value_in_same_box(lbl_b, "Date of Blrth", "date")
        if same_dob:
            fields["date_of_birth"] = (same_dob, lbl_b.confidence)
            methods["date_of_birth"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.08, field_type="date")
            if val_b:
                dob_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if dob_val:
                    fields["date_of_birth"] = (dob_val, val_b.confidence)
                    methods["date_of_birth"] = "label_anchor"

    if "date_of_birth" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.62 <= b.ymin <= 0.75 and 0.18 <= b.xmin <= 0.40:
                dob_cand = clean_field_value(b.text, "date", confidence=b.confidence)
                if dob_cand:
                    fields["date_of_birth"] = (dob_cand, b.confidence)
                    methods["date_of_birth"] = "pattern_fallback"
                    break

    if "date_of_birth" not in fields:
        dates = re.findall(r"\b\d{2}[/\-.,]?\d{2}[/\-.,]\d{4}\b", full_text)
        if dates:
            cleaned_d = clean_field_value(dates[0], "date", confidence=0.85)
            if cleaned_d:
                fields["date_of_birth"] = (cleaned_d, 0.85)
                methods["date_of_birth"] = "pattern_fallback"

    return fields, methods


def extract_aadhaar_anchored(
    boxes: List[OCRBox],
    full_text: str = "",
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    fields: Dict[str, Tuple[str, float]] = {}
    methods: Dict[str, str] = {}

    # 1. Aadhaar Number (12 digits 4-4-4, or masked XXXX XXXX 1107)
    for b in boxes:
        digits = re.sub(r"[^\d]", "", b.text)
        if len(digits) == 12:
            formatted = f"{digits[0:4]} {digits[4:8]} {digits[8:12]}"
            fields["aadhaar_number"] = (formatted, b.confidence)
            methods["aadhaar_number"] = "label_anchor"
            break
        m_masked = re.search(r"\b([Xx*]{4}[\s\-_]*[Xx*]{4}[\s\-_]*(\d{4}))\b", b.text)
        if m_masked:
            last4 = m_masked.group(2)
            fields["aadhaar_number"] = (f"XXXX XXXX {last4}", b.confidence)
            fields["aadhaar_last4"] = (last4, b.confidence)
            methods["aadhaar_number"] = "label_anchor_masked"
            break

    if "aadhaar_number" not in fields:
        m = re.search(r"\b(\d{4}\s+\d{4}\s+\d{4})\b", full_text)
        if not m:
            m = re.search(r"\b(\d{12})\b", full_text)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            fields["aadhaar_number"] = (f"{digits[0:4]} {digits[4:8]} {digits[8:12]}", 0.90)
            methods["aadhaar_number"] = "pattern_fallback"
        else:
            m_masked = re.search(r"\b([Xx*]{4}[\s\-_]*[Xx*]{4}[\s\-_]*(\d{4}))\b", full_text)
            if not m_masked:
                m_masked = re.search(r"([Xx*]{4,8}[\s\-_]*[Xx*]{0,4}[\s\-_]*(\d{4}))", full_text)
            if m_masked:
                last4 = m_masked.group(2) if m_masked.lastindex and m_masked.lastindex >= 2 else m_masked.group(1)[-4:]
                fields["aadhaar_number"] = (f"XXXX XXXX {last4}", 0.90)
                fields["aadhaar_last4"] = (last4, 0.90)
                methods["aadhaar_number"] = "pattern_fallback_masked"

    # 2. Date of Birth
    dob_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["date_of_birth"])
    dob_box = None
    if dob_lbl_res:
        lbl_b, lbl_syn = dob_lbl_res
        dob_box = lbl_b
        same_dob = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_dob:
            fields["date_of_birth"] = (same_dob, lbl_b.confidence)
            methods["date_of_birth"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date")
            if val_b:
                dob_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if dob_val:
                    fields["date_of_birth"] = (dob_val, val_b.confidence)
                    methods["date_of_birth"] = "label_anchor"

    if "date_of_birth" not in fields:
        m = re.search(r"(?:DOB|DATE OF BIRTH)\s*[:\-]?\s*(\d{2}[/,.\-]\d{2}[/,.\-]\d{4})", full_text, re.I)
        if m:
            fields["date_of_birth"] = (clean_field_value(m.group(1), "date", confidence=0.85), 0.85)
            methods["date_of_birth"] = "pattern_fallback"

    # 3. Gender
    gender_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["gender"])
    if gender_lbl_res:
        lbl_b, lbl_syn = gender_lbl_res
        same_g = find_value_in_same_box(lbl_b, lbl_syn, "gender")
        if same_g:
            fields["gender"] = (same_g, lbl_b.confidence)
            methods["gender"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="gender")
            if val_b:
                g_val = clean_field_value(val_b.text, "gender", confidence=val_b.confidence)
                if g_val:
                    fields["gender"] = (g_val, val_b.confidence)
                    methods["gender"] = "label_anchor"

    if "gender" not in fields:
        if re.search(r"\b(?:FEMALE)\b", full_text, re.I):
            fields["gender"] = ("Female", 0.95)
            methods["gender"] = "pattern_fallback"
        elif re.search(r"\b(?:MALE)\b", full_text, re.I):
            fields["gender"] = ("Male", 0.95)
            methods["gender"] = "pattern_fallback"

    # 4. Name (Aadhaar cards print English name directly above DOB)
    if dob_box is not None:
        candidates = []
        for b in boxes:
            if b is dob_box:
                continue
            if b.ymin < dob_box.ymin and b.ymin >= 0.10:
                txt = b.clean_text()
                if not is_blocklisted_label(txt) and any(c.isalpha() for c in txt):
                    if b.xmin <= 0.60:
                        candidates.append((dob_box.ymin - b.ymax, b))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            best_name_box = candidates[0][1]
            fields["name"] = (clean_field_value(best_name_box.text, "text", confidence=best_name_box.confidence), best_name_box.confidence)
            methods["name"] = "label_anchor"

    # 5. Address (User instruction: Return LOW_CONFIDENCE on all types)
    fields["address"] = ("LOW_CONFIDENCE", 0.0)
    methods["address"] = "label_anchor"

    return fields, methods


def extract_voter_anchored(
    boxes: List[OCRBox],
    full_text: str = "",
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    fields: Dict[str, Tuple[str, float]] = {}
    methods: Dict[str, str] = {}

    # 1. EPIC Number
    epic_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["epic_number"])
    if epic_lbl_res:
        lbl_b, lbl_syn = epic_lbl_res
        same_epic = find_value_in_same_box(lbl_b, lbl_syn, "epic")
        if same_epic:
            fields["epic_number"] = (same_epic, lbl_b.confidence)
            methods["epic_number"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="epic") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.15, field_type="epic")
            if val_b:
                epic_val = clean_field_value(val_b.text, "epic", confidence=val_b.confidence)
                if epic_val:
                    fields["epic_number"] = (epic_val, val_b.confidence)
                    methods["epic_number"] = "label_anchor"

    if "epic_number" not in fields:
        for b in boxes:
            if b.ymin <= 0.28:
                epic_cand = clean_field_value(b.text, "epic", confidence=b.confidence)
                if epic_cand:
                    fields["epic_number"] = (epic_cand, b.confidence)
                    methods["epic_number"] = "pattern_fallback"
                    break

    if "epic_number" not in fields:
        m = re.search(r"\b([A-Z]{3}[0-9]{7})\b", full_text.upper())
        if m:
            fields["epic_number"] = (m.group(1), 0.90)
            methods["epic_number"] = "pattern_fallback"

    # 2. Name
    name_lbl_res = None
    for cand_syn in [
        "Elector's Name:", "Elector's Name", "Electors Name", "Elector s Name:", "Elector s Name",
        "Electors Mame:", "Electors Mame", "Electot", "Voter Name:", "Voter Name"
    ]:
        res = find_label_box(boxes, [cand_syn])
        if res and "FATHER" not in res[0].text.upper():
            name_lbl_res = res
            break

    if name_lbl_res:
        lbl_b, lbl_syn = name_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.10)
        if val_b:
            name_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if name_val and not is_blocklisted_label(name_val) and len(name_val) >= 3:
                fields["name"] = (name_val, val_b.confidence)
                methods["name"] = "label_anchor"
        if "name" not in fields:
            same_name = find_value_in_same_box(lbl_b, lbl_syn, "text")
            if same_name and not is_blocklisted_label(same_name) and len(same_name) >= 3:
                fields["name"] = (same_name, lbl_b.confidence)
                methods["name"] = "label_anchor"

    if "name" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.26 <= b.ymin <= 0.38 and 0.18 <= b.xmin <= 0.65:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    fields["name"] = (t, b.confidence)
                    methods["name"] = "pattern_fallback"
                    break

    # 3. Father's Name
    fn_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["father_name"])
    if fn_lbl_res:
        lbl_b, lbl_syn = fn_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.12)
        if val_b:
            fn_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if fn_val and not is_blocklisted_label(fn_val) and len(fn_val) >= 3:
                fields["father_name"] = (fn_val, val_b.confidence)
                methods["father_name"] = "label_anchor"
        if "father_name" not in fields:
            same_fn = find_value_in_same_box(lbl_b, lbl_syn, "text")
            if same_fn and not is_blocklisted_label(same_fn) and len(same_fn) >= 3:
                fields["father_name"] = (same_fn, lbl_b.confidence)
                methods["father_name"] = "label_anchor"

    if "father_name" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.40 <= b.ymin <= 0.55 and 0.18 <= b.xmin <= 0.65:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    fields["father_name"] = (t, b.confidence)
                    methods["father_name"] = "pattern_fallback"
                    break

    # 4. Gender
    gender_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["gender"])
    if gender_lbl_res:
        lbl_b, lbl_syn = gender_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes, field_type="gender")
        if val_b:
            g_val = clean_field_value(val_b.text, "gender", confidence=val_b.confidence)
            if g_val:
                fields["gender"] = (g_val, val_b.confidence)
                methods["gender"] = "label_anchor"
        if "gender" not in fields:
            same_g = find_value_in_same_box(lbl_b, lbl_syn, "gender")
            if same_g:
                fields["gender"] = (same_g, lbl_b.confidence)
                methods["gender"] = "label_anchor"

    if "gender" not in fields:
        if re.search(r"\b(?:FEMALE)\b", full_text, re.I):
            fields["gender"] = ("Female", 0.95)
            methods["gender"] = "pattern_fallback"
        elif re.search(r"\b(?:MALE)\b", full_text, re.I):
            fields["gender"] = ("Male", 0.95)
            methods["gender"] = "pattern_fallback"

    # 5. Date of Birth
    dob_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["date_of_birth"])
    if dob_lbl_res:
        lbl_b, lbl_syn = dob_lbl_res
        same_dob = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_dob:
            fields["date_of_birth"] = (same_dob, lbl_b.confidence)
            methods["date_of_birth"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date")
            if val_b:
                dob_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if dob_val:
                    fields["date_of_birth"] = (dob_val, val_b.confidence)
                    methods["date_of_birth"] = "label_anchor"

    if "date_of_birth" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.55 <= b.ymin <= 0.65 and 0.30 <= b.xmin <= 0.60:
                dob_cand = clean_field_value(b.text, "date", confidence=b.confidence)
                if dob_cand:
                    fields["date_of_birth"] = (dob_cand, b.confidence)
                    methods["date_of_birth"] = "pattern_fallback"
                    break

    if "date_of_birth" not in fields:
        m = re.search(r"\b(\d{2}[/,.\-]?\d{2}[/,.\-]\d{4})\b", full_text)
        if m:
            cleaned_d = clean_field_value(m.group(1), "date", confidence=0.85)
            if cleaned_d:
                fields["date_of_birth"] = (cleaned_d, 0.85)
                methods["date_of_birth"] = "pattern_fallback"

    # 6. Address (User instruction: Return LOW_CONFIDENCE on all types)
    fields["address"] = ("LOW_CONFIDENCE", 0.0)
    methods["address"] = "label_anchor"

    return fields, methods


def extract_passport_anchored(
    boxes: List[OCRBox],
    full_text: str = "",
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    fields: Dict[str, Tuple[str, float]] = {}
    methods: Dict[str, str] = {}

    # 1. Passport Number
    p_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["passport_number"])
    if p_lbl_res:
        lbl_b, lbl_syn = p_lbl_res
        same_p = find_value_in_same_box(lbl_b, lbl_syn, "passport_number")
        if same_p:
            fields["passport_number"] = (same_p, lbl_b.confidence)
            methods["passport_number"] = "label_anchor"
        else:
            val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.15, field_type="passport_number") or find_right_neighbor_box(lbl_b, boxes, field_type="passport_number")
            if val_b:
                p_val = clean_field_value(val_b.text, "passport_number", confidence=val_b.confidence)
                if p_val:
                    fields["passport_number"] = (p_val, val_b.confidence)
                    methods["passport_number"] = "label_anchor"

    if "passport_number" not in fields:
        for b in boxes:
            if 0.12 <= b.ymin <= 0.28 and 0.50 <= b.xmin <= 0.95:
                p_cand = clean_field_value(b.text, "passport_number", confidence=b.confidence)
                if p_cand:
                    fields["passport_number"] = (p_cand, b.confidence)
                    methods["passport_number"] = "pattern_fallback"
                    break

    if "passport_number" not in fields:
        m = re.search(r"\b([A-Z][0-9]{7,8})\b", full_text.upper())
        if m:
            fields["passport_number"] = (m.group(1), 0.85)
            methods["passport_number"] = "pattern_fallback"

    # 2. Surname
    sur_lbl_res = find_label_box(boxes, [
        "Surname / Nom:", "Surname / Nom", "Surname", "Nom:", "Nom",
        "Sumame", "Bumame", "Surame", "Suman", "Sumname", "Noni", "St4n"
    ])
    if sur_lbl_res:
        lbl_b, lbl_syn = sur_lbl_res
        val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.14)
        if val_b:
            sur_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if sur_val and not is_blocklisted_label(sur_val) and len(sur_val) >= 3:
                fields["surname"] = (sur_val.upper(), val_b.confidence)
                methods["surname"] = "label_anchor"
        if "surname" not in fields:
            same_sur = find_value_in_same_box(lbl_b, lbl_syn, "text")
            if same_sur and not is_blocklisted_label(same_sur) and len(same_sur) >= 3:
                fields["surname"] = (same_sur.upper(), lbl_b.confidence)
                methods["surname"] = "label_anchor"

    if "surname" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.24 <= b.ymin <= 0.33 and 0.18 <= b.xmin <= 0.45:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    fields["surname"] = (t.upper(), b.confidence)
                    methods["surname"] = "pattern_fallback"
                    break

    # 3. Given Names
    giv_lbl_res = find_label_box(boxes, [
        "Given Names / Prénoms:", "Given Names / Prenoms:", "Given Names", "Prénoms", "Prenoms",
        "Given Nanes", "Grenines", "Cheniut", "Prenon", "Penon", "Fenon"
    ])
    if giv_lbl_res:
        lbl_b, lbl_syn = giv_lbl_res
        val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.14)
        if val_b:
            giv_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if giv_val and not is_blocklisted_label(giv_val) and len(giv_val) >= 3:
                fields["given_names"] = (giv_val.upper(), val_b.confidence)
                methods["given_names"] = "label_anchor"
        if "given_names" not in fields:
            same_giv = find_value_in_same_box(lbl_b, lbl_syn, "text")
            if same_giv and not is_blocklisted_label(same_giv) and len(same_giv) >= 3:
                fields["given_names"] = (same_giv.upper(), lbl_b.confidence)
                methods["given_names"] = "label_anchor"

    if "given_names" not in fields:
        for b in sorted(boxes, key=lambda x: (x.ymin, x.xmin)):
            if 0.33 <= b.ymin <= 0.44 and 0.18 <= b.xmin <= 0.45:
                t = clean_field_value(b.text, "text", confidence=b.confidence)
                if t and not is_blocklisted_label(t) and any(c.isalpha() for c in t) and len(t) >= 3:
                    fields["given_names"] = (t.upper(), b.confidence)
                    methods["given_names"] = "pattern_fallback"
                    break

    # TD3 MRZ Line 1 cross-check/recovery for names
    td3_m = re.search(r"P<[A-Z0-9]{3}([A-Z]+)<<([A-Z<]+)", full_text.upper().replace(" ", ""))
    if td3_m:
        td3_sur = td3_m.group(1).replace("<", "").strip()
        td3_giv = td3_m.group(2).replace("<", " ").strip()
        if "surname" not in fields or is_blocklisted_label(fields["surname"][0]):
            fields["surname"] = (td3_sur, 0.95)
            methods["surname"] = "pattern_fallback"
        if "given_names" not in fields or is_blocklisted_label(fields["given_names"][0]):
            fields["given_names"] = (td3_giv, 0.95)
            methods["given_names"] = "pattern_fallback"

    # 4. Nationality
    nat_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["nationality"])
    if nat_lbl_res:
        lbl_b, _ = nat_lbl_res
        val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.10) or find_right_neighbor_box(lbl_b, boxes)
        if val_b:
            nat_val = clean_field_value(val_b.text, "nationality", confidence=val_b.confidence)
            if nat_val and not is_blocklisted_label(nat_val):
                fields["nationality"] = (nat_val, val_b.confidence)
                methods["nationality"] = "label_anchor"

    if "nationality" not in fields:
        m = re.search(r"\b(UTO|IND|USA|GBR|FRA|DEU|CAN|AUS)\b", full_text.upper())
        if m:
            fields["nationality"] = (m.group(1), 0.85)
            methods["nationality"] = "pattern_fallback"

    # 5. Date of Birth
    dob_lbl_res = find_label_box(boxes, ["Date of birth / Date de naissance:", "Date of birth", "Date de naissance", "DOB"])
    if dob_lbl_res:
        lbl_b, lbl_syn = dob_lbl_res
        same_dob = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_dob:
            fields["date_of_birth"] = (same_dob, lbl_b.confidence)
            methods["date_of_birth"] = "label_anchor"
        else:
            val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.10, field_type="date") or find_right_neighbor_box(lbl_b, boxes, field_type="date")
            if val_b:
                dob_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if dob_val:
                    fields["date_of_birth"] = (dob_val, val_b.confidence)
                    methods["date_of_birth"] = "label_anchor"

    # 6. Sex (Priority Fix: single character handling for {M, F, X})
    sex_lbl_res = find_label_box(boxes, [
        "Sex / Sexe:", "Sex / Sexe", "Sex", "Sexe", "Sex:", "Sexe:",
        "8ex / Sexe", "Bex / Sexe:", "Bex / Sexe", "524 / Sexe", "Se] / Sexe"
    ])
    if sex_lbl_res:
        lbl_b, lbl_syn = sex_lbl_res
        same_s = find_value_in_same_box(lbl_b, lbl_syn, "sex")
        if same_s:
            fields["sex"] = (same_s, lbl_b.confidence)
            methods["sex"] = "label_anchor"
        else:
            val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.18, max_dx=0.35, field_type="sex") or find_right_neighbor_box(lbl_b, boxes, max_dx=0.40, max_dy=0.10, field_type="sex")
            if val_b:
                sex_val = clean_field_value(val_b.text, "sex", confidence=val_b.confidence)
                if sex_val in ("M", "F", "X"):
                    fields["sex"] = (sex_val, val_b.confidence)
                    methods["sex"] = "label_anchor"

    if "sex" not in fields:
        for b in boxes:
            if 0.50 <= b.ymin <= 0.68 and 0.18 <= b.xmin <= 0.35:
                s_cand = clean_field_value(b.text, "sex", confidence=b.confidence)
                if s_cand in ("M", "F", "X"):
                    fields["sex"] = (s_cand, b.confidence)
                    methods["sex"] = "pattern_fallback"
                    break

    # 7. Date of Expiry
    exp_lbl_res = find_label_box(boxes, ["Date of expiry / Date d'expiration:", "Date of expiry", "Date d'expiration", "Expiry"])
    if exp_lbl_res:
        lbl_b, lbl_syn = exp_lbl_res
        same_exp = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_exp:
            fields["date_of_expiry"] = (same_exp, lbl_b.confidence)
            methods["date_of_expiry"] = "label_anchor"
        else:
            val_b = find_below_neighbor_box(lbl_b, boxes, max_dy=0.10, field_type="date") or find_right_neighbor_box(lbl_b, boxes, field_type="date")
            if val_b:
                exp_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if exp_val:
                    fields["date_of_expiry"] = (exp_val, val_b.confidence)
                    methods["date_of_expiry"] = "label_anchor"

    for b in boxes:
        d_cand = clean_field_value(b.text, "date", confidence=b.confidence)
        if d_cand:
            if "date_of_birth" not in fields and 0.44 <= b.ymin <= 0.56 and 0.35 <= b.xmin <= 0.75:
                fields["date_of_birth"] = (d_cand, b.confidence)
                methods["date_of_birth"] = "pattern_fallback"
            elif "date_of_expiry" not in fields and 0.56 <= b.ymin <= 0.70 and 0.35 <= b.xmin <= 0.75:
                fields["date_of_expiry"] = (d_cand, b.confidence)
                methods["date_of_expiry"] = "pattern_fallback"

    # MRZ fallback for passport (names, sex, dates, nationality)
    mrz_boxes = [(b, b.text.replace(" ", "").upper()) for b in boxes if len(b.text.replace(" ", "")) >= 25]
    for b, line in mrz_boxes:
        # TD3 line 1: P<UTO[SURNAME]<<[GIVEN_NAMES]...
        m_name = re.search(r"P[<K<][A-Z0-9]{3}([A-Z]+)<<([A-Z< ]+)", line)
        if m_name:
            sur_mrz = m_name.group(1).replace("<", "").strip()
            giv_mrz = m_name.group(2).replace("<", " ").strip()
            giv_mrz = re.sub(r"\s+", " ", giv_mrz).strip()
            if "surname" not in fields or is_blocklisted_label(fields["surname"][0]) or len(fields["surname"][0]) <= 2:
                fields["surname"] = (sur_mrz, b.confidence)
                methods["surname"] = "pattern_fallback"
            if "given_names" not in fields or is_blocklisted_label(fields["given_names"][0]) or len(fields["given_names"][0]) <= 2:
                fields["given_names"] = (giv_mrz, b.confidence)
                methods["given_names"] = "pattern_fallback"

        # TD3 line 2
        m_icao = re.search(r"UT[O0](\d{6})[0-9<]?([MFX0O])(\d{6})", line)
        if not m_icao:
            m_icao = re.search(r"[A-Z0-9]{9}[0-9<][A-Z0-9]{3}(\d{6})[0-9<]?([MFX0O])(\d{6})", line)
        if not m_icao:
            m_icao = re.search(r"(\d{6})[0-9<]?([MFX0O])(\d{6})", line)
        if m_icao:
            if "nationality" not in fields:
                fields["nationality"] = ("UTO", b.confidence)
                methods["nationality"] = "pattern_fallback"
            dob_raw = m_icao.group(1)
            if "date_of_birth" not in fields:
                yy = int(dob_raw[0:2])
                yyyy = f"19{yy:02d}" if yy >= 30 else f"20{yy:02d}"
                fields["date_of_birth"] = (f"{dob_raw[4:6]}/{dob_raw[2:4]}/{yyyy}", b.confidence)
                methods["date_of_birth"] = "pattern_fallback"
            if "sex" not in fields:
                s_raw = m_icao.group(2).upper()
                if s_raw in ("M", "F", "X"):
                    fields["sex"] = (s_raw, b.confidence)
                    methods["sex"] = "pattern_fallback"
                elif s_raw in ("0", "O"):
                    if b.confidence < CONFIDENCE_REPAIR_THRESHOLD:
                        log_repair("sex", s_raw, "M", b.confidence, "MRZ line 2 OCR 0/O -> M (low confidence)")
                        fields["sex"] = ("M", b.confidence)
                        methods["sex"] = "pattern_fallback"
                    else:
                        fields["sex"] = (s_raw, b.confidence)
                        methods["sex"] = "pattern_fallback"
            exp_raw = m_icao.group(3)
            if "date_of_expiry" not in fields:
                yy = int(exp_raw[0:2])
                yyyy = f"20{yy:02d}" if yy < 50 else f"19{yy:02d}"
                fields["date_of_expiry"] = (f"{exp_raw[4:6]}/{exp_raw[2:4]}/{yyyy}", b.confidence)
                methods["date_of_expiry"] = "pattern_fallback"

    return fields, methods


def extract_visa_anchored(
    boxes: List[OCRBox],
    full_text: str = "",
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    fields: Dict[str, Tuple[str, float]] = {}
    methods: Dict[str, str] = {}

    v_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["visa_number"])
    p_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["passport_number"])
    v_lbl_b = v_lbl_res[0] if v_lbl_res else None
    p_lbl_b = p_lbl_res[0] if p_lbl_res else None

    v_num_res, p_num_res = disambiguate_numbers_by_proximity(boxes, v_lbl_b, p_lbl_b)
    if v_num_res:
        fields["visa_number"] = v_num_res
        methods["visa_number"] = "label_anchor"
    if p_num_res:
        fields["passport_number"] = p_num_res
        methods["passport_number"] = "label_anchor"

    if "visa_number" not in fields:
        m = re.search(r"\b(V[0-9]{7,9})\b", full_text.upper())
        if m:
            fields["visa_number"] = (m.group(1), 0.85)
            methods["visa_number"] = "pattern_fallback"
    if "passport_number" not in fields:
        m = re.search(r"\b([A-Z][0-9]{7,8})\b", full_text.upper())
        if m and m.group(1) != fields.get("visa_number", ("", 0))[0]:
            fields["passport_number"] = (m.group(1), 0.85)
            methods["passport_number"] = "pattern_fallback"

    # Name (Format on card: 'Surname, Given Names')
    name_lbl_res = find_label_box(boxes, ["Name / Nom:", "Name / Nom", "Name:", "Name"])
    if name_lbl_res:
        lbl_b, _ = name_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.12)
        if val_b:
            name_val = clean_field_value(val_b.text, "text", confidence=val_b.confidence)
            if name_val and not is_blocklisted_label(name_val) and not any(c.isdigit() for c in name_val):
                fields["name"] = (name_val, val_b.confidence)
                methods["name"] = "label_anchor"
                if "," in name_val:
                    p = name_val.split(",", 1)
                    fields["surname"] = (p[0].strip(), val_b.confidence)
                    fields["given_names"] = (p[1].strip(), val_b.confidence)
                    methods["surname"] = "label_anchor"
                    methods["given_names"] = "label_anchor"
                elif ";" in name_val:
                    p = name_val.split(";", 1)
                    fields["surname"] = (p[0].strip(), val_b.confidence)
                    fields["given_names"] = (p[1].strip(), val_b.confidence)
                    methods["surname"] = "label_anchor"
                    methods["given_names"] = "label_anchor"
                else:
                    parts = name_val.split()
                    if len(parts) >= 2:
                        fields["surname"] = (parts[0], val_b.confidence)
                        fields["given_names"] = (" ".join(parts[1:]), val_b.confidence)
                        methods["surname"] = "label_anchor"
                        methods["given_names"] = "label_anchor"

    # Nationality
    nat_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["nationality"])
    if nat_lbl_res:
        lbl_b, lbl_syn = nat_lbl_res
        val_b = find_right_neighbor_box(lbl_b, boxes) or find_below_neighbor_box(lbl_b, boxes, max_dy=0.10)
        if val_b:
            nat_val = clean_field_value(val_b.text, "nationality", confidence=val_b.confidence)
            if nat_val and not is_blocklisted_label(nat_val):
                fields["nationality"] = (nat_val, val_b.confidence)
                methods["nationality"] = "label_anchor"

    # Date of Birth
    dob_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["date_of_birth"])
    if dob_lbl_res:
        lbl_b, lbl_syn = dob_lbl_res
        same_dob = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_dob:
            fields["date_of_birth"] = (same_dob, lbl_b.confidence)
            methods["date_of_birth"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.10, field_type="date")
            if val_b:
                dob_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if dob_val:
                    fields["date_of_birth"] = (dob_val, val_b.confidence)
                    methods["date_of_birth"] = "label_anchor"

    # Sex / Gender
    sex_lbl_res = find_label_box(boxes, ["Sex", "Gender", "Sex / Sexe", "Sexe"])
    if sex_lbl_res:
        lbl_b, lbl_syn = sex_lbl_res
        same_s = find_value_in_same_box(lbl_b, lbl_syn, "sex")
        if same_s:
            fields["sex"] = (same_s, lbl_b.confidence)
            methods["sex"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="sex") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.10, field_type="sex")
            if val_b:
                s_val = clean_field_value(val_b.text, "sex", confidence=val_b.confidence)
                if s_val in ("M", "F", "X", "MALE", "FEMALE"):
                    s_norm = "M" if s_val.startswith("M") else ("F" if s_val.startswith("F") else "X")
                    fields["sex"] = (s_norm, val_b.confidence)
                    methods["sex"] = "label_anchor"

    # Valid From
    vf_lbl_res = find_label_box(boxes, FIELD_LABEL_SYNONYMS["valid_from"])
    if vf_lbl_res:
        lbl_b, lbl_syn = vf_lbl_res
        same_vf = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_vf:
            fields["valid_from"] = (same_vf, lbl_b.confidence)
            methods["valid_from"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.12, field_type="date")
            if val_b:
                vf_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if vf_val:
                    fields["valid_from"] = (vf_val, val_b.confidence)
                    methods["valid_from"] = "label_anchor"

    # Date of Expiry
    exp_lbl_res = find_label_box(boxes, ["Expiry / Until:", "Expiry", "Until:", "Date of Expiry", "Expiry Date"])
    if exp_lbl_res:
        lbl_b, lbl_syn = exp_lbl_res
        same_exp = find_value_in_same_box(lbl_b, lbl_syn, "date")
        if same_exp:
            fields["date_of_expiry"] = (same_exp, lbl_b.confidence)
            methods["date_of_expiry"] = "label_anchor"
        else:
            val_b = find_right_neighbor_box(lbl_b, boxes, field_type="date") or find_below_neighbor_box(lbl_b, boxes, max_dy=0.12, field_type="date")
            if val_b:
                exp_val = clean_field_value(val_b.text, "date", confidence=val_b.confidence)
                if exp_val:
                    fields["date_of_expiry"] = (exp_val, val_b.confidence)
                    methods["date_of_expiry"] = "label_anchor"

    for b in boxes:
        d_cand = clean_field_value(b.text, "date", confidence=b.confidence)
        if d_cand:
            if "valid_from" not in fields and 0.35 <= b.ymin <= 0.65 and 0.10 <= b.xmin <= 0.50:
                fields["valid_from"] = (d_cand, b.confidence)
                methods["valid_from"] = "pattern_fallback"
            elif "date_of_expiry" not in fields and 0.35 <= b.ymin <= 0.78 and 0.40 <= b.xmin <= 0.85:
                fields["date_of_expiry"] = (d_cand, b.confidence)
                methods["date_of_expiry"] = "pattern_fallback"

    return fields, methods



# ---------------------------------------------------------------------------
# Cascade Orchestrator
# ---------------------------------------------------------------------------

def extract_fields_cascade(
    boxes: List[OCRBox],
    doc_type: str,
    full_text: str = "",
    template_crops_fn: Optional[Any] = None,
    image: Optional[np.ndarray] = None,
) -> Tuple[Dict[str, Tuple[str, float]], Dict[str, str]]:
    doc_type_key = doc_type.lower().strip()
    if doc_type_key in ("pan", "national_id_pan"):
        fields, methods = extract_pan_anchored(boxes, full_text, image=image)
    elif doc_type_key in ("aadhaar", "national_id_aadhaar", "national_id"):
        fields, methods = extract_aadhaar_anchored(boxes, full_text)
    elif doc_type_key in ("voter", "voter_id", "national_id_voter"):
        fields, methods = extract_voter_anchored(boxes, full_text)
    elif doc_type_key in ("passport",):
        fields, methods = extract_passport_anchored(boxes, full_text)
    elif doc_type_key in ("visa",):
        fields, methods = extract_visa_anchored(boxes, full_text)
    else:
        fields, methods = {}, {}

    if template_crops_fn and doc_type_key not in ("voter", "voter_id", "national_id_voter"):
        try:
            missing_fields = template_crops_fn(doc_type_key, fields.keys())
            for k, (v, c) in missing_fields.items():
                if k not in fields and v and not is_blocklisted_label(v):
                    fields[k] = (v, c)
                    methods[k] = "coordinate_template"
        except Exception as e:
            logger.debug(f"Coordinate template fallback note: {e}")

    return fields, methods


def boxes_from_raw_results(
    raw_results: List[Any],
    img_shape: Tuple[int, int] = (1000, 1000),
    image: Optional[np.ndarray] = None,
) -> List[OCRBox]:
    h, w = img_shape[:2]
    ocr_boxes: List[OCRBox] = []

    for item in raw_results:
        char_confs = None
        if isinstance(item, (list, tuple)) and len(item) == 3 and isinstance(item[0], (list, tuple)):
            bbox, text, conf = item
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            ymin = max(0.0, min(1.0, min(ys) / h))
            xmin = max(0.0, min(1.0, min(xs) / w))
            ymax = max(0.0, min(1.0, max(ys) / h))
            xmax = max(0.0, min(1.0, max(xs) / w))
            t_str = str(text).strip()
            if image is not None and len(t_str) == 10 and any(c.isdigit() for c in t_str):
                y1, y2 = max(0, int(ymin * h)), min(h, int(ymax * h))
                x1, x2 = max(0, int(xmin * w)), min(w, int(xmax * w))
                if y2 > y1 and x2 > x1:
                    char_confs = get_char_confidences_from_crop(image[y1:y2, x1:x2], t_str)
            ocr_boxes.append(OCRBox(text=t_str, confidence=float(conf), bbox=(ymin, xmin, ymax, xmax), char_confidences=char_confs))

        elif isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], (tuple, list)):
            poly = item[0]
            text = str(item[1][0]).strip()
            conf = float(item[1][1])
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            ymin = max(0.0, min(1.0, min(ys) / h))
            xmin = max(0.0, min(1.0, min(xs) / w))
            ymax = max(0.0, min(1.0, max(ys) / h))
            xmax = max(0.0, min(1.0, max(xs) / w))
            t_str = str(text).strip()
            if image is not None and len(t_str) == 10 and any(c.isdigit() for c in t_str):
                y1, y2 = max(0, int(ymin * h)), min(h, int(ymax * h))
                x1, x2 = max(0, int(xmin * w)), min(w, int(xmax * w))
                if y2 > y1 and x2 > x1:
                    char_confs = get_char_confidences_from_crop(image[y1:y2, x1:x2], t_str)
            ocr_boxes.append(OCRBox(text=t_str, confidence=conf, bbox=(ymin, xmin, ymax, xmax), char_confidences=char_confs))

        elif isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
            text, conf = item
            idx = len(ocr_boxes)
            ymin = min(0.95, 0.05 + idx * 0.04)
            ymax = min(0.99, ymin + 0.035)
            ocr_boxes.append(OCRBox(text=str(text).strip(), confidence=float(conf), bbox=(ymin, 0.05, ymax, 0.95)))

    return ocr_boxes
