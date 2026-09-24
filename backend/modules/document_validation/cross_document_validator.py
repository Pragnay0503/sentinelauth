"""
cross_document_validator.py - Cross-document identity field validation.
Compares stable identity fields (Name, DOB, Nationality, Gender) across 3+ documents
from the same session to detect inconsistencies as a strong fraud signal.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

try:
    from ...utils.serialization import to_json_safe
except (ImportError, ValueError):
    try:
        from backend.utils.serialization import to_json_safe
    except ImportError:
        def to_json_safe(obj):
            return obj

from .mrz_cross_validator import (
    _normalize_date_iso,
    _normalize_gender,
    _normalize_string,
)


# Stable identity fields to compare across documents of the same person
CROSS_DOC_FIELDS = ["name", "date_of_birth", "address", "nationality", "gender"]


COUNTRY_ALIASES = {
    "INDIA": "IND", "IND": "IND", "INDIAN": "IND",
    "UNITED STATES": "USA", "USA": "USA", "UNITED STATES OF AMERICA": "USA", "AMERICAN": "USA",
    "UNITED KINGDOM": "GBR", "GBR": "GBR", "UK": "GBR", "BRITISH": "GBR",
    "GERMANY": "DEU", "DEU": "DEU", "DEUTSCHLAND": "DEU", "GERMAN": "DEU",
    "FRANCE": "FRA", "FRA": "FRA", "FRENCH": "FRA",
    "CANADA": "CAN", "CAN": "CAN", "CANADIAN": "CAN",
    "AUSTRALIA": "AUS", "AUS": "AUS", "AUSTRALIAN": "AUS",
    "CHINA": "CHN", "CHN": "CHN", "CHINESE": "CHN",
    "JAPAN": "JPN", "JPN": "JPN", "JAPANESE": "JPN",
    "MEXICO": "MEX", "MEX": "MEX", "MEXICAN": "MEX",
    "PAKISTAN": "PAK", "PAK": "PAK", "PAKISTANI": "PAK",
    "BANGLADESH": "BGD", "BGD": "BGD", "BANGLADESHI": "BGD",
    "NEPAL": "NPL", "NPL": "NPL", "NEPALESE": "NPL",
    "SRI LANKA": "LKA", "LKA": "LKA", "SRI LANKAN": "LKA",
}


def _unwrap_field_value(raw: Any) -> Optional[str]:
    """Unwrap a field value from various wrapper structures (FieldResult, dict, tuple, scalar)."""
    if raw is None:
        return None
    if hasattr(raw, "value"):
        val = raw.value
    elif isinstance(raw, dict):
        val = raw.get("value") if raw.get("value") is not None else raw.get("raw_value")
    elif isinstance(raw, (tuple, list)) and len(raw) > 0:
        val = raw[0]
    else:
        val = raw

    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def extract_raw_fields_dict(scan_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a flat dict of field_name -> value from various scan structures:
    - Full scan payload with 'ocr.extracted_fields' / 'ocr.visual_fields'
    - 'holder_name' and 'document_number' at payload or link root
    - Top-level 'extracted_fields'
    - Flat mock dictionary (e.g. {"name": "...", "dob": "..."})
    """
    if not isinstance(scan_data, dict):
        return {}

    fields: Dict[str, Any] = {}
    payload = scan_data.get("scan_payload")
    if not isinstance(payload, dict):
        payload = scan_data

    # 1. Top-level holder_name / document_number
    for k in ("holder_name", "document_number"):
        for source in (scan_data, payload):
            if isinstance(source, dict) and source.get(k) is not None:
                fields[k] = source[k]

    # 2. ocr.extracted_fields and ocr.visual_fields
    ocr = payload.get("ocr") if isinstance(payload, dict) else {}
    if isinstance(ocr, dict):
        ext = ocr.get("extracted_fields")
        if isinstance(ext, dict):
            fields.update(ext)
        vis = ocr.get("visual_fields")
        if isinstance(vis, dict):
            for vk, vv in vis.items():
                if vk not in fields or not fields[vk]:
                    fields[vk] = vv

    # 3. Direct 'extracted_fields'
    if "extracted_fields" in payload and isinstance(payload["extracted_fields"], dict):
        for ek, ev in payload["extracted_fields"].items():
            if ek not in fields or not fields[ek]:
                fields[ek] = ev

    # 4. Flat keys from payload or scan_data (excluding known internal sub-dicts)
    skip_keys = {
        "ocr", "validation", "tampering", "biometrics", "risk", "historical_check",
        "scan_payload", "scan_id", "session_id", "timestamp", "checkpoint",
        "officer_id", "document_image_url", "ela_heatmap_url", "document_type",
        "document_label", "status", "stage", "progress"
    }
    for src in (payload, scan_data):
        if isinstance(src, dict):
            for k, v in src.items():
                if k not in skip_keys and k not in fields and v is not None:
                    fields[k] = v

    # 5. Unwrap all values
    clean: Dict[str, str] = {}
    for k, v in fields.items():
        unwrapped = _unwrap_field_value(v)
        if unwrapped:
            clean[k] = unwrapped

    return clean


def normalize_fields(extracted_fields: Dict[str, Any], document_type: str = "") -> Dict[str, Optional[str]]:
    """
    Standardize field keys across document types (Passport, Aadhaar, PAN, DL, Voter ID):
    - name: name | full_name | surname + given_names | holder_name
    - date_of_birth: dob | date_of_birth | birth_date | yob | year_of_birth
    - document_number: passport_number | aadhaar_number | pan_number | dl_number | id_number | epic_number | visa_number
    - address: address | permanent_address | residential_address
    - nationality: nationality | country | issuing_country
    - gender: gender | sex
    """
    raw_dict = extract_raw_fields_dict(extracted_fields)
    canonical: Dict[str, Optional[str]] = {
        "name": None,
        "date_of_birth": None,
        "document_number": None,
        "address": None,
        "nationality": None,
        "gender": None,
    }

    # -------------------------------------------------------------
    # 1. Name Standardization
    # -------------------------------------------------------------
    surname = raw_dict.get("surname")
    given = raw_dict.get("given_names") or raw_dict.get("given_name") or raw_dict.get("first_name")
    primary_name = raw_dict.get("name") or raw_dict.get("full_name") or raw_dict.get("holder_name")

    if primary_name:
        p_name = primary_name.strip()
        # If primary_name is just the surname and given_names is separate (e.g. Passport)
        if given and _normalize_string(given) not in _normalize_string(p_name):
            canonical["name"] = f"{given} {p_name}".strip()
        else:
            canonical["name"] = p_name
    elif surname and given:
        canonical["name"] = f"{given} {surname}".strip()
    elif surname:
        canonical["name"] = surname.strip()
    elif given:
        canonical["name"] = given.strip()

    # -------------------------------------------------------------
    # 2. Date of Birth Standardization
    # -------------------------------------------------------------
    dob_val = None
    for k in ("date_of_birth", "dob", "birth_date", "date_of_birth_/_yob"):
        if k in raw_dict and raw_dict[k]:
            dob_val = raw_dict[k].strip()
            break
    if not dob_val:
        for k in ("year_of_birth", "yob"):
            if k in raw_dict and raw_dict[k]:
                dob_val = raw_dict[k].strip()
                break
    canonical["date_of_birth"] = dob_val

    # -------------------------------------------------------------
    # 3. Document Number Standardization
    # -------------------------------------------------------------
    doc_num_val = None
    for k in (
        "document_number", "passport_number", "aadhaar_number", "pan_number",
        "dl_number", "id_number", "epic_number", "visa_number"
    ):
        if k in raw_dict and raw_dict[k]:
            doc_num_val = raw_dict[k].strip()
            break
    canonical["document_number"] = doc_num_val

    # -------------------------------------------------------------
    # 4. Address Standardization
    # -------------------------------------------------------------
    addr_val = None
    for k in ("address", "permanent_address", "residential_address"):
        if k in raw_dict and raw_dict[k]:
            addr_val = raw_dict[k].strip()
            break
    canonical["address"] = addr_val

    # -------------------------------------------------------------
    # 5. Nationality Standardization
    # -------------------------------------------------------------
    nat_val = None
    for k in ("nationality", "country", "issuing_country", "nation"):
        if k in raw_dict and raw_dict[k]:
            nat_val = raw_dict[k].strip()
            break
    canonical["nationality"] = nat_val

    # -------------------------------------------------------------
    # 6. Gender Standardization
    # -------------------------------------------------------------
    gen_val = None
    for k in ("gender", "sex"):
        if k in raw_dict and raw_dict[k]:
            gen_val = raw_dict[k].strip()
            break
    canonical["gender"] = gen_val

    return canonical


def _normalize_field_value(field_key: str, raw_value: str) -> str:
    """Normalize field values for cross-document comparison."""
    if not raw_value:
        return ""
    if field_key == "date_of_birth":
        iso = _normalize_date_iso(raw_value)
        return iso if iso else _normalize_string(raw_value)
    if field_key == "gender":
        return _normalize_gender(raw_value)
    if field_key == "nationality":
        norm = _normalize_string(raw_value)
        return COUNTRY_ALIASES.get(norm, norm)
    if field_key == "address":
        return _normalize_string(raw_value)
    return _normalize_string(raw_value)


def _names_are_consistent(name_a: str, name_b: str) -> bool:
    """
    Check if two names refer to the same individual using:
    - Exact match after normalization
    - Token set equivalence (handles 'KAJA KARTHIKEYA REDDY' == 'KARTHIKEYA REDDY KAJA')
    - Token subset (handles 'KARTHIKEYA REDDY' inside 'KAJA KARTHIKEYA REDDY')
    - High token intersection (difference of <= 1 token for middle initials/suffixes)
    - Fuzzy string similarity >= 0.85
    """
    norm_a = _normalize_string(name_a)
    norm_b = _normalize_string(name_b)
    if not norm_a or not norm_b:
        return True  # Cannot declare mismatch if one is missing

    if norm_a == norm_b:
        return True

    tok_a = set(norm_a.split())
    tok_b = set(norm_b.split())

    # Exact token match regardless of order
    if tok_a == tok_b:
        return True

    # Subset match (e.g. initial or truncated middle name)
    if tok_a.issubset(tok_b) or tok_b.issubset(tok_a):
        return True

    # High token intersection
    intersection = tok_a.intersection(tok_b)
    min_len = min(len(tok_a), len(tok_b))
    if min_len >= 2 and len(intersection) >= min_len - 1:
        return True

    # Fuzzy sequence matcher
    ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    return ratio >= 0.85


def _dobs_are_consistent(dob_a: str, dob_b: str) -> bool:
    """
    Check if two DOB values are consistent:
    - Normalized ISO YYYY-MM-DD equality
    - Year-only match if one document only contains 4-digit Year-of-Birth (e.g. Aadhaar YOB)
    """
    if not dob_a or not dob_b:
        return True

    iso_a = _normalize_date_iso(dob_a)
    iso_b = _normalize_date_iso(dob_b)

    if iso_a and iso_b:
        return iso_a == iso_b

    # Fallback: check 4-digit year match
    if len(dob_a.strip()) == 4 and dob_a.strip().isdigit() and iso_b:
        return iso_b.startswith(dob_a.strip())
    if len(dob_b.strip()) == 4 and dob_b.strip().isdigit() and iso_a:
        return iso_a.startswith(dob_b.strip())

    return _normalize_string(dob_a) == _normalize_string(dob_b)


def _addresses_are_consistent(addr_a: str, addr_b: str) -> bool:
    """
    Check if two addresses are consistent across documents:
    - Significant token overlap (city, state, PIN code)
    - Substring containment
    - High word intersection
    """
    norm_a = _normalize_string(addr_a)
    norm_b = _normalize_string(addr_b)
    if not norm_a or not norm_b:
        return True

    if norm_a in norm_b or norm_b in norm_a:
        return True

    # Significant words (length >= 3)
    words_a = {w for w in norm_a.split() if len(w) >= 3 and not w.isdigit()}
    words_b = {w for w in norm_b.split() if len(w) >= 3 and not w.isdigit()}

    if not words_a or not words_b:
        return True

    common = words_a.intersection(words_b)
    overlap_ratio = len(common) / min(len(words_a), len(words_b))
    return len(common) >= 2 or overlap_ratio >= 0.40


def _values_are_consistent(field_key: str, val_a: str, val_b: str) -> bool:
    """Dispatches comparison based on field type."""
    if field_key == "name":
        return _names_are_consistent(val_a, val_b)
    if field_key == "date_of_birth":
        return _dobs_are_consistent(val_a, val_b)
    if field_key == "address":
        return _addresses_are_consistent(val_a, val_b)
    if field_key == "gender":
        return _normalize_gender(val_a) == _normalize_gender(val_b)
    if field_key == "nationality":
        norm_a = _normalize_string(val_a)
        norm_b = _normalize_string(val_b)
        code_a = COUNTRY_ALIASES.get(norm_a, norm_a)
        code_b = COUNTRY_ALIASES.get(norm_b, norm_b)
        return code_a == code_b
    return _normalize_string(val_a) == _normalize_string(val_b)


def _extract_field_from_scan(scan_payload: Dict[str, Any], *field_aliases: str) -> Optional[str]:
    """Backward-compatible field extractor using alias list."""
    fields = extract_raw_fields_dict(scan_payload)
    for alias in field_aliases:
        if alias in fields and fields[alias]:
            return str(fields[alias]).strip()
    return None


def cross_validate_session_documents(
    session_scans: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Cross-validate identity fields across all documents in a session.
    Standardizes fields across Passport, Aadhaar, PAN, DL, and Voter ID,
    skipping fields with insufficient sources and flagging real mismatches.

    Args:
        session_scans: List of session scan link dicts or payloads.

    Returns:
        Dict with:
            - field_consistency: dict[field_key -> consistency_result]
            - has_cross_document_mismatch: bool
            - corroboration_factor: float (0.0 to 1.0)
            - flags: list[str]
            - summary: str
    """
    if not session_scans or len(session_scans) < 2:
        res = {
            "field_consistency": {},
            "has_cross_document_mismatch": False,
            "corroboration_factor": 0.0,
            "consistent_count": 0,
            "verifiable_count": 0,
            "total_documents": len(session_scans) if session_scans else 0,
            "mismatched_fields": [],
            "flags": [],
            "summary": "Single document verified. Cross-document validation activates when corroborating documents are uploaded.",
        }
        return to_json_safe(res)

    # 1. Normalize fields for each document
    normalized_docs = []
    for link in session_scans:
        doc_type = link.get("document_type") or ""
        doc_label = link.get("document_label") or link.get("document_type") or "Document"
        scan_id = link.get("scan_id", "")
        # Extract and normalize
        norm_fields = normalize_fields(link, document_type=doc_type)
        normalized_docs.append({
            "scan_id": scan_id,
            "document": doc_label,
            "document_type": doc_type,
            "canonical_fields": norm_fields,
        })

    field_consistency: Dict[str, Any] = {}
    consistent_count = 0
    verifiable_count = 0
    mismatch_flags = []

    # 2. Compare each comparable field
    for field_key in CROSS_DOC_FIELDS:
        doc_values = []
        na_docs = []
        for doc in normalized_docs:
            raw_val = doc["canonical_fields"].get(field_key)
            if raw_val is not None:
                s_val = str(raw_val).strip()
                if s_val.lower() == "not applicable for this document type":
                    na_docs.append(doc["document"])
                    continue
                if s_val:
                    norm_val = _normalize_field_value(field_key, s_val)
                    doc_values.append({
                        "document": doc["document"],
                        "scan_id": doc["scan_id"],
                        "value": s_val,
                        "normalized": norm_val,
                    })

        # Check for insufficient documents (< 2 docs with this field)
        if len(doc_values) < 2:
            na_msg = f" (not applicable for: {', '.join(na_docs)})" if na_docs else ""
            field_consistency[field_key] = {
                "field": field_key,
                "values": doc_values,
                "not_applicable_documents": na_docs,
                "consistent": None,
                "match": None,
                "reason": "insufficient_documents_with_field",
                "status": "insufficient_corroboration",
                "flag": None,
                "message": (
                    f"Field '{field_key}' was only found in {len(doc_values)} document(s){na_msg}; "
                    "cannot cross-validate."
                ),
            }
            continue

        # Check all pairs for consistency
        is_consistent = True
        for i in range(len(doc_values)):
            for j in range(i + 1, len(doc_values)):
                val_i = doc_values[i]["value"]
                val_j = doc_values[j]["value"]
                if not _values_are_consistent(field_key, val_i, val_j):
                    is_consistent = False
                    break
            if not is_consistent:
                break

        verifiable_count += 1
        if is_consistent:
            consistent_count += 1
            field_consistency[field_key] = {
                "field": field_key,
                "values": doc_values,
                "consistent": True,
                "match": True,
                "status": "verified_consistent",
                "flag": None,
                "message": f"'{field_key}' is consistent across all {len(doc_values)} documents.",
            }
        else:
            flag = "CROSS_DOCUMENT_MISMATCH"
            disagreement_details = [
                f"{entry['document']}: '{entry['value']}'" for entry in doc_values
            ]
            mismatch_flags.append(flag)
            field_consistency[field_key] = {
                "field": field_key,
                "values": doc_values,
                "consistent": False,
                "match": False,
                "status": "mismatch",
                "flag": flag,
                "message": (
                    f"'{field_key}' does NOT match across documents: "
                    + " | ".join(disagreement_details)
                ),
            }

    corroboration_factor = (
        round(float(consistent_count) / float(verifiable_count), 3) if verifiable_count > 0 else 0.0
    )
    has_mismatch = len(mismatch_flags) > 0

    mismatched_fields = [
        k for k, v in field_consistency.items() if v.get("flag") == "CROSS_DOCUMENT_MISMATCH"
    ]

    if has_mismatch:
        summary = (
            f"CROSS_DOCUMENT_MISMATCH detected on: {', '.join(mismatched_fields)}. "
            f"Corroboration: {consistent_count}/{verifiable_count} fields consistent."
        )
    elif verifiable_count == 0:
        summary = "No common identity fields found across documents for cross-validation."
    else:
        summary = (
            f"All {verifiable_count} verifiable fields are consistent across documents. "
            f"Strong identity corroboration confirmed."
        )

    result = {
        "field_consistency": field_consistency,
        "has_cross_document_mismatch": has_mismatch,
        "mismatched_fields": mismatched_fields,
        "corroboration_factor": float(corroboration_factor),
        "consistent_count": int(consistent_count),
        "verifiable_count": int(verifiable_count),
        "total_documents": len(session_scans),
        "flags": list(set(mismatch_flags)),
        "summary": summary,
    }

    return to_json_safe(result)
