"""
cross_checker.py - Compare MRZ-extracted fields against visual-OCR fields.
Flags mismatches as an early tampering/forgery signal.
Fully self-contained.
"""
from __future__ import annotations
import re
from typing import Dict, List, Tuple

from .mrz_parser import MRZData


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    s = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return " ".join(s.split())


def _normalise_date(date: str) -> str:
    """
    Accept DD/MM/YYYY or YYMMDD or DD-MM-YYYY.
    Converts everything to DDMMYYYY for comparison.
    """
    # Already DD/MM/YYYY or DD-MM-YYYY
    m = re.fullmatch(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})", date.strip())
    if m:
        return m.group(1) + m.group(2) + m.group(3)
    # YYMMDD (MRZ)
    m = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", date.strip())
    if m:
        yy, mm, dd = m.group(1), m.group(2), m.group(3)
        century = "20" if int(yy) < 70 else "19"
        return dd + mm + century + yy
    # Plain 8-digit DDMMYYYY
    m = re.fullmatch(r"(\d{8})", date.strip())
    if m:
        return m.group(1)
    return date.strip().lower()


def _values_match(a: str, b: str, field_type: str = "text") -> bool:
    if not a or not b:
        return True  # can't compare if one side missing
    if field_type == "date":
        return _normalise_date(a) == _normalise_date(b)
    if field_type == "name":
        na, nb = _normalise_name(a), _normalise_name(b)
        return na == nb or na in nb or nb in na
    return a.strip().lower() == b.strip().lower()


# ---------------------------------------------------------------------------
# Overlap map: MRZ field name -> (visual field name, type)
# ---------------------------------------------------------------------------

_OVERLAP_MAP: List[Tuple[str, str, str]] = [
    ("surname",      "name",             "name"),
    ("given_names",  "given_names",      "name"),
    ("doc_number",   "passport_number",  "text"),
    ("doc_number",   "id_number",        "text"),
    ("nationality",  "nationality",      "text"),
    ("dob",          "date_of_birth",    "date"),
    ("expiry",       "date_of_expiry",   "date"),
    ("expiry",       "expiry",           "date"),
    ("sex",          "gender",           "text"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cross_check(
    mrz: MRZData,
    visual_fields: Dict[str, Tuple[str, float]],
) -> Dict[str, bool]:
    """
    Compare overlapping fields between MRZ and visual OCR.

    Returns:
        {field_name: mismatch_bool}  - True means a mismatch (potential tampering).
    """
    mismatches: Dict[str, bool] = {}
    mrz_dict = mrz.as_dict() if mrz else {}

    for mrz_key, visual_key, field_type in _OVERLAP_MAP:
        mrz_val = mrz_dict.get(mrz_key, "")
        if not mrz_val:
            continue
        if visual_key not in visual_fields:
            continue
        vis_val, _ = visual_fields[visual_key]
        mismatch = not _values_match(mrz_val, vis_val, field_type)
        # Use visual_key as canonical field name for the report
        if mismatch:
            mismatches[visual_key] = True

    return mismatches
