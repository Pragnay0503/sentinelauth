"""
mrz_cross_validator.py — Cross-validate visual OCR fields against MRZ parsed fields.

Compares printed visual zone text with ICAO 9303 MRZ fields, performing format
normalization (ISO dates, uppercase names, stripped punctuation) and per-field
MRZ check digit verification.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .schemas import FieldCrossValidationItem


def _normalize_string(text: str) -> str:
    """Normalize string by removing diacritics, punctuation, and excess spaces."""
    if not text:
        return ""
    # Remove accents/diacritics
    nfkd = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Keep alphanumeric and spaces
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", cleaned).upper()
    return " ".join(cleaned.split())


def _normalize_date_iso(date_str: str, is_expiry: bool = False) -> Optional[str]:
    """
    Convert various date formats into standard ISO YYYY-MM-DD string.
    Handles:
      - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
      - YYYY-MM-DD, YYYY/MM/DD
      - YYMMDD (MRZ format)
      - DD Mon YYYY / DD-Mon-YYYY (e.g. 15 AUG 1985)
    """
    if not date_str:
        return None
    s = str(date_str).strip()

    # 1. Check if already ISO YYYY-MM-DD
    m_iso = re.fullmatch(r"(\d{4})[/\-.](\d{2})[/\-.](\d{2})", s)
    if m_iso:
        y, m, d = m_iso.group(1), m_iso.group(2), m_iso.group(3)
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # 2. DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m_dmy = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m_dmy:
        d, m, y = m_dmy.group(1), m_dmy.group(2), m_dmy.group(3)
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # 3. Textual month format: e.g. 15 AUG 1985, 15-Aug-1985
    m_txt = re.fullmatch(r"(\d{1,2})[/\-.\s]([A-Za-z]{3,9})[/\-.\s](\d{2,4})", s)
    if m_txt:
        d, mon_str, yr = m_txt.group(1), m_txt.group(2)[:3].upper(), m_txt.group(3)
        month_map = {
            "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
            "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
            "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
        }
        if mon_str in month_map:
            m = month_map[mon_str]
            if len(yr) == 2:
                yy_int = int(yr)
                if is_expiry:
                    century = "20" if yy_int < 70 else "19"
                else:
                    century = "20" if yy_int <= 30 else "19"
                yr = century + yr
            return f"{yr}-{m}-{d.zfill(2)}"

    # 4. MRZ 6-digit YYMMDD
    clean_digits = re.sub(r"\D", "", s)
    if len(clean_digits) == 6:
        yy = clean_digits[:2]
        mm = clean_digits[2:4]
        dd = clean_digits[4:]
        yy_int = int(yy)
        if is_expiry:
            century = "20" if yy_int < 70 else "19"
        else:
            century = "20" if yy_int <= 30 else "19"
        return f"{century}{yy}-{mm}-{dd}"

    return None


def _normalize_doc_number(num_str: str) -> str:
    """Normalize passport or document number (alphanumeric, no fillers)."""
    if not num_str:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(num_str)).upper()
    return cleaned.rstrip("<")


def _normalize_gender(gender_str: str) -> str:
    """Normalize gender to standard single char 'M', 'F', 'X'."""
    if not gender_str:
        return ""
    g = gender_str.strip().upper()
    if g.startswith("M"):
        return "M"
    if g.startswith("F"):
        return "F"
    if g in ("X", "O", "OTHER", "NON-BINARY"):
        return "X"
    return g[:1]


def _names_match(visual_name: str, mrz_name: str) -> bool:
    """
    Compare visual name against MRZ name using token-set comparison.
    Handles 'DOE JOHN' vs 'JOHN DOE', middle initials, etc.
    """
    v_norm = _normalize_string(visual_name)
    m_norm = _normalize_string(mrz_name)
    if not v_norm or not m_norm:
        return True

    if v_norm == m_norm:
        return True

    v_tokens = set(v_norm.split())
    m_tokens = set(m_norm.split())

    # If all visual tokens are in MRZ or vice-versa
    if v_tokens.issubset(m_tokens) or m_tokens.issubset(v_tokens):
        return True

    # High token intersection
    intersection = v_tokens.intersection(m_tokens)
    if len(intersection) >= max(1, min(len(v_tokens), len(m_tokens)) - 1):
        return True

    return False


def cross_validate_mrz_vs_visual(
    visual_fields: Dict[str, Any],
    mrz_dict: Dict[str, Any],
    mrz_checksums: Optional[Dict[str, bool]] = None
) -> Dict[str, FieldCrossValidationItem]:
    """
    Perform cross-validation between visual printed fields and parsed MRZ.
    
    Args:
        visual_fields: Map of visual field names to raw string values or FieldResult objects.
        mrz_dict: Map of MRZ fields (surname, given_names, doc_number, dob, sex, expiry, nationality).
        mrz_checksums: Map of per-field checksum results e.g. {'doc_number': True, 'dob': True, 'expiry': True}.
    
    Returns:
        Dict mapping field names (e.g. 'date_of_birth', 'passport_number') to FieldCrossValidationItem.
    """
    if not mrz_dict:
        return {}

    mrz_checksums = mrz_checksums or {}
    results: Dict[str, FieldCrossValidationItem] = {}

    def get_val(container: Dict[str, Any], *keys: str) -> Optional[str]:
        for k in keys:
            if k in container:
                v = container[k]
                if hasattr(v, "value"):
                    return str(v.value).strip()
                if isinstance(v, tuple) and len(v) > 0:
                    return str(v[0]).strip()
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if v is not None and str(v).strip():
                    return str(v).strip()
        return None

    # -------------------------------------------------------------
    # 1. Date of Birth
    # -------------------------------------------------------------
    vis_dob = get_val(visual_fields, "date_of_birth", "dob", "birth_date", "date_of_birth_/_yob")
    mrz_dob = get_val(mrz_dict, "dob")
    if vis_dob and mrz_dob:
        iso_vis = _normalize_date_iso(vis_dob, is_expiry=False)
        iso_mrz = _normalize_date_iso(mrz_dob, is_expiry=False)
        chk_dob = mrz_checksums.get("dob")
        # Check digit defaults to True if not explicitly False
        chk_valid = True if chk_dob is not False else False

        match = (iso_vis == iso_mrz) if (iso_vis and iso_mrz) else (vis_dob.strip() == mrz_dob.strip())
        
        flag = None
        if not match and chk_valid:
            flag = "VISUAL_MRZ_MISMATCH"
        elif not match and not chk_valid:
            flag = "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID"
        elif match and not chk_valid:
            flag = "MRZ_CHECKSUM_INVALID"

        results["date_of_birth"] = FieldCrossValidationItem(
            visual_value=vis_dob,
            mrz_value=mrz_dob,
            match=match,
            mrz_checksum_valid=chk_valid,
            flag=flag
        )

    # -------------------------------------------------------------
    # 2. Passport / Document Number
    # -------------------------------------------------------------
    vis_doc_num = get_val(visual_fields, "passport_number", "document_number", "id_number", "visa_number")
    mrz_doc_num = get_val(mrz_dict, "doc_number", "passport_number")
    if vis_doc_num and mrz_doc_num:
        clean_vis = _normalize_doc_number(vis_doc_num)
        clean_mrz = _normalize_doc_number(mrz_doc_num)
        chk_doc = mrz_checksums.get("doc_number")
        chk_valid = True if chk_doc is not False else False

        match = (clean_vis == clean_mrz)
        flag = None
        if not match and chk_valid:
            flag = "VISUAL_MRZ_MISMATCH"
        elif not match and not chk_valid:
            flag = "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID"
        elif match and not chk_valid:
            flag = "MRZ_CHECKSUM_INVALID"

        results["passport_number"] = FieldCrossValidationItem(
            visual_value=vis_doc_num,
            mrz_value=mrz_doc_num,
            match=match,
            mrz_checksum_valid=chk_valid,
            flag=flag
        )

    # -------------------------------------------------------------
    # 3. Date of Expiry
    # -------------------------------------------------------------
    vis_exp = get_val(visual_fields, "date_of_expiry", "expiry_date", "expiry", "valid_until")
    mrz_exp = get_val(mrz_dict, "expiry")
    if vis_exp and mrz_exp:
        iso_vis = _normalize_date_iso(vis_exp, is_expiry=True)
        iso_mrz = _normalize_date_iso(mrz_exp, is_expiry=True)
        chk_exp = mrz_checksums.get("expiry")
        chk_valid = True if chk_exp is not False else False

        match = (iso_vis == iso_mrz) if (iso_vis and iso_mrz) else (vis_exp.strip() == mrz_exp.strip())
        flag = None
        if not match and chk_valid:
            flag = "VISUAL_MRZ_MISMATCH"
        elif not match and not chk_valid:
            flag = "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID"
        elif match and not chk_valid:
            flag = "MRZ_CHECKSUM_INVALID"

        results["date_of_expiry"] = FieldCrossValidationItem(
            visual_value=vis_exp,
            mrz_value=mrz_exp,
            match=match,
            mrz_checksum_valid=chk_valid,
            flag=flag
        )

    # -------------------------------------------------------------
    # 4. Holder Name
    # -------------------------------------------------------------
    vis_name = get_val(visual_fields, "name", "full_name", "holder_name")
    mrz_surname = get_val(mrz_dict, "surname") or ""
    mrz_given = get_val(mrz_dict, "given_names") or ""
    mrz_full_name = f"{mrz_surname} {mrz_given}".strip() or get_val(mrz_dict, "name")

    if vis_name and mrz_full_name:
        match = _names_match(vis_name, mrz_full_name)
        flag = "VISUAL_MRZ_MISMATCH" if not match else None

        results["name"] = FieldCrossValidationItem(
            visual_value=vis_name,
            mrz_value=mrz_full_name,
            match=match,
            mrz_checksum_valid=True,
            flag=flag
        )

    # -------------------------------------------------------------
    # 5. Gender / Sex
    # -------------------------------------------------------------
    vis_sex = get_val(visual_fields, "gender", "sex")
    mrz_sex = get_val(mrz_dict, "sex", "gender")
    if vis_sex and mrz_sex:
        norm_vis = _normalize_gender(vis_sex)
        norm_mrz = _normalize_gender(mrz_sex)
        match = (norm_vis == norm_mrz)
        flag = "VISUAL_MRZ_MISMATCH" if not match else None

        results["gender"] = FieldCrossValidationItem(
            visual_value=vis_sex,
            mrz_value=mrz_sex,
            match=match,
            mrz_checksum_valid=True,
            flag=flag
        )

    # -------------------------------------------------------------
    # 6. Nationality / Country
    # -------------------------------------------------------------
    vis_nat = get_val(visual_fields, "nationality", "country")
    mrz_nat = get_val(mrz_dict, "nationality", "country")
    if vis_nat and mrz_nat:
        clean_vis = _normalize_string(vis_nat)
        clean_mrz = _normalize_string(mrz_nat)
        match = (clean_vis == clean_mrz or clean_mrz in clean_vis or clean_vis in clean_mrz)
        flag = "VISUAL_MRZ_MISMATCH" if not match else None

        results["nationality"] = FieldCrossValidationItem(
            visual_value=vis_nat,
            mrz_value=mrz_nat,
            match=match,
            mrz_checksum_valid=True,
            flag=flag
        )

    return results
