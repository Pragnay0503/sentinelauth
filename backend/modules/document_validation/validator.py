"""
validator.py — Main orchestrator for Module 2 Document Validation.
Accepts an OCRResult, executes rules engine, logical consistency checks,
blacklist verification, pulls forward Module 1 red flags, and returns ValidationResult.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .blacklist import check_blacklist
from .mrz_cross_validator import cross_validate_mrz_vs_visual
from .rules_engine import (
    check_date_consistency,
    extract_field_value,
    validate_aadhaar_rules,
    validate_age_plausibility,
    validate_dl_rules,
    validate_gender,
    validate_pan_rules,
    validate_passport_rules,
    validate_permit_rules,
    validate_visa_rules,
    validate_voter_rules,
)
from .schemas import FieldCrossValidationItem, Severity, ValidationResult, Violation


def validate_document(ocr_data: Any) -> ValidationResult:
    """
    Main entry point for Document Validation (Module 2).
    Accepts OCRResult Pydantic model, dictionary, or duck-typed object.
    """
    violations: List[Violation] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    # Extract document_type
    if hasattr(ocr_data, "document_type"):
        raw_doc_type = str(getattr(ocr_data.document_type, "value", ocr_data.document_type)).lower()
    elif isinstance(ocr_data, dict):
        raw_doc_type = str(ocr_data.get("document_type", "unknown")).lower()
    else:
        raw_doc_type = "unknown"

    # Extract fields dictionary
    if hasattr(ocr_data, "extracted_fields"):
        fields = getattr(ocr_data, "extracted_fields") or {}
    elif isinstance(ocr_data, dict):
        fields = ocr_data.get("extracted_fields") or {}
    else:
        fields = {}

    # 1. Pull forward Module 1 flags (Requirement 4)
    # -------------------------------------------------------------
    # Flag A: document_type_mismatch & type_mismatch_warning
    doc_type_mismatch = False
    type_mismatch_warning = None
    if hasattr(ocr_data, "document_type_mismatch"):
        doc_type_mismatch = bool(ocr_data.document_type_mismatch)
    elif isinstance(ocr_data, dict):
        doc_type_mismatch = bool(ocr_data.get("document_type_mismatch", False))

    if hasattr(ocr_data, "type_mismatch_warning") and getattr(ocr_data, "type_mismatch_warning"):
        type_mismatch_warning = getattr(ocr_data, "type_mismatch_warning")
    elif isinstance(ocr_data, dict) and ocr_data.get("type_mismatch_warning"):
        type_mismatch_warning = ocr_data.get("type_mismatch_warning")

    if type_mismatch_warning:
        warnings.insert(0, type_mismatch_warning)
        details["type_mismatch_warning"] = type_mismatch_warning

    if doc_type_mismatch:
        v = Violation(
            field="document_type",
            rule_violated=type_mismatch_warning or "Document type mismatch: Auto-detected document type conflicts with declared document type",
            severity=Severity.HIGH.value,
        )
        violations.append(v)
        if not type_mismatch_warning:
            warnings.append("Declared document type does not match visual anchor phrases found on the document.")

    # Flag B: low_confidence_but_format_valid
    low_conf_format = False
    if hasattr(ocr_data, "low_confidence_but_format_valid"):
        low_conf_format = bool(ocr_data.low_confidence_but_format_valid)
    elif isinstance(ocr_data, dict):
        low_conf_format = bool(ocr_data.get("low_confidence_but_format_valid", False))

    if low_conf_format:
        v = Violation(
            field="ocr_confidence",
            rule_violated="Low OCR text confidence despite valid format checksum (potential low-resolution scan or tampering)",
            severity=Severity.MEDIUM.value,
        )
        violations.append(v)
        warnings.append("Low OCR confidence score: Verify physical security features manually.")

    # Flag C: MRZ vs Visual Cross-Validation (Per-field check digits and mismatch detection)
    visual_fields_map: Dict[str, Any] = {}
    if hasattr(ocr_data, "visual_fields") and getattr(ocr_data, "visual_fields"):
        visual_fields_map = getattr(ocr_data, "visual_fields")
    elif isinstance(ocr_data, dict) and ocr_data.get("visual_fields"):
        visual_fields_map = ocr_data.get("visual_fields")
    else:
        visual_fields_map = fields

    mrz_dict: Dict[str, Any] = {}
    if hasattr(ocr_data, "mrz_parsed") and getattr(ocr_data, "mrz_parsed"):
        mrz_dict = getattr(ocr_data, "mrz_parsed")
    elif isinstance(ocr_data, dict) and ocr_data.get("mrz_parsed"):
        mrz_dict = ocr_data.get("mrz_parsed")
    elif hasattr(ocr_data, "mrz_data") and getattr(ocr_data, "mrz_data"):
        mrz_obj = getattr(ocr_data, "mrz_data")
        mrz_dict = mrz_obj.as_dict() if hasattr(mrz_obj, "as_dict") else dict(mrz_obj)

    mrz_checksums: Dict[str, bool] = {}
    if hasattr(ocr_data, "mrz_checksums") and getattr(ocr_data, "mrz_checksums"):
        mrz_checksums = getattr(ocr_data, "mrz_checksums")
    elif isinstance(ocr_data, dict) and ocr_data.get("mrz_checksums"):
        mrz_checksums = ocr_data.get("mrz_checksums")
    elif hasattr(ocr_data, "mrz_data") and hasattr(getattr(ocr_data, "mrz_data"), "checksums_ok"):
        mrz_checksums = getattr(ocr_data, "mrz_data").checksums_ok

    field_cross_validation: Dict[str, FieldCrossValidationItem] = {}
    if mrz_dict:
        field_cross_validation = cross_validate_mrz_vs_visual(
            visual_fields=visual_fields_map,
            mrz_dict=mrz_dict,
            mrz_checksums=mrz_checksums
        )

    for f_name, item in field_cross_validation.items():
        field_title = f_name.replace("_", " ").title()
        if item.flag == "VISUAL_MRZ_MISMATCH":
            v = Violation(
                field=f_name,
                rule_violated=f"{field_title}: mismatch between printed value ('{item.visual_value}') and MRZ ('{item.mrz_value}') while MRZ check digit is valid",
                severity=Severity.CRITICAL.value,
            )
            violations.append(v)
            warnings.append(f"Tampering alert: Printed {field_title} ('{item.visual_value}') conflicts with verified MRZ ('{item.mrz_value}').")
        elif item.flag == "MRZ_CHECKSUM_INVALID":
            v = Violation(
                field=f_name,
                rule_violated=f"{field_title}: MRZ check digit validation failed (MRZ value: '{item.mrz_value}')",
                severity=Severity.CRITICAL.value,
            )
            violations.append(v)
            warnings.append(f"MRZ Integrity alert: Check digit failed for {field_title} ('{item.mrz_value}').")
        elif item.flag == "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID":
            v = Violation(
                field=f_name,
                rule_violated=f"{field_title}: mismatch between printed value ('{item.visual_value}') and invalid MRZ ('{item.mrz_value}')",
                severity=Severity.CRITICAL.value,
            )
            violations.append(v)
            warnings.append(f"Tampering alert: Printed {field_title} ('{item.visual_value}') differs and MRZ check digit failed.")

    # Flag E: Whole-MRZ checksum failure
    mrz_app = getattr(ocr_data, "mrz_applicable", False) if hasattr(ocr_data, "mrz_applicable") else (ocr_data.get("mrz_applicable", False) if isinstance(ocr_data, dict) else False)
    mrz_pass = getattr(ocr_data, "mrz_validation_passed", None) if hasattr(ocr_data, "mrz_validation_passed") else (ocr_data.get("mrz_validation_passed") if isinstance(ocr_data, dict) else None)
    if mrz_app and mrz_pass is False and not any(v.field in field_cross_validation for v in violations):
        v = Violation(
            field="mrz_checksum",
            rule_violated="MRZ ICAO 9303 checksum validation failed",
            severity=Severity.CRITICAL.value,
        )
        violations.append(v)
        warnings.append("MRZ checksum validation failed: Possible forged or invalid passport/visa.")


    # 2. Extract Key Identity Data (Run ONLY checks valid for detected type)
    # -------------------------------------------------------------
    # Fallback to MRZ-extracted values when printed OCR fails to find a field
    if mrz_dict:
        if not extract_field_value(fields, "passport_number", "document_number", "id_number", "doc_number", "visa_number"):
            m_doc = mrz_dict.get("doc_number") or mrz_dict.get("passport_number") or mrz_dict.get("visa_number")
            if m_doc:
                target_key = "visa_number" if "visa" in raw_doc_type else "passport_number"
                fields[target_key] = m_doc
        if not extract_field_value(fields, "name", "full_name"):
            m_sur = str(mrz_dict.get("surname", "")).strip()
            m_giv = str(mrz_dict.get("given_names", "")).strip()
            m_name = f"{m_giv} {m_sur}".strip() or m_sur or m_giv or str(mrz_dict.get("name", "")).strip()
            if m_name:
                fields["name"] = m_name
        if not extract_field_value(fields, "nationality"):
            if mrz_dict.get("nationality"):
                fields["nationality"] = mrz_dict["nationality"]
        if not extract_field_value(fields, "date_of_birth", "dob", "birth_date"):
            if mrz_dict.get("dob"):
                fields["date_of_birth"] = mrz_dict["dob"]
        if not extract_field_value(fields, "date_of_expiry", "expiry_date", "valid_until", "expiry"):
            if mrz_dict.get("expiry"):
                fields["date_of_expiry"] = mrz_dict["expiry"]

    doc_num = extract_field_value(fields, "document_number", "id_number", "passport_number", "visa_number", "pan_number", "aadhaar_number", "driving_licence_number", "license_number", "epic_number", "doc_number")
    name = extract_field_value(fields, "name", "full_name", "holder_name", "surname")
    dob_str = extract_field_value(fields, "date_of_birth", "dob", "birth_date", "date_of_birth_/_yob", "yob")
    issue_str = extract_field_value(fields, "date_of_issue", "issue_date", "valid_from", "issued_on")

    carries_expiry = not ("pan" in raw_doc_type or "aadhaar" in raw_doc_type)
    if carries_expiry:
        expiry_str = extract_field_value(fields, "date_of_expiry", "expiry_date", "valid_until", "expiry", "valid_till")
    else:
        expiry_str = "not applicable for this document type"

    carries_nationality = bool("passport" in raw_doc_type or "visa" in raw_doc_type)
    nat_str = extract_field_value(fields, "nationality", "country") if carries_nationality else "not applicable for this document type"

    details["extracted_document_number"] = doc_num
    details["extracted_name"] = name
    details["extracted_dob"] = dob_str
    details["extracted_expiry"] = expiry_str
    details["extracted_nationality"] = nat_str

    # 3. Logical Date Consistency & Plausibility Checks
    # -------------------------------------------------------------
    effective_expiry_for_check = expiry_str if (carries_expiry and expiry_str != "not applicable for this document type") else None
    date_violations, is_expired = check_date_consistency(dob_str, issue_str, effective_expiry_for_check)
    violations.extend(date_violations)
    if is_expired and carries_expiry:
        warnings.append("Document has expired and cannot be accepted for border clearance.")

    # Cross-field checks (gender enum, age plausibility)
    if "pan" not in raw_doc_type:
        violations.extend(validate_gender(fields))
    violations.extend(validate_age_plausibility(fields))

    # 4. Per-Document-Type Format & Field Rules (Run ONLY rules for detected type)
    # -------------------------------------------------------------
    if "passport" in raw_doc_type:
        violations.extend(validate_passport_rules(fields, mrz_dict=mrz_dict))
    elif "visa" in raw_doc_type:
        violations.extend(validate_visa_rules(fields, mrz_dict=mrz_dict))
    elif "pan" in raw_doc_type:
        violations.extend(validate_pan_rules(fields))
    elif "aadhaar" in raw_doc_type:
        violations.extend(validate_aadhaar_rules(fields))
    elif "voter" in raw_doc_type:
        violations.extend(validate_voter_rules(fields))
    elif "driving" in raw_doc_type or "license" in raw_doc_type:
        violations.extend(validate_dl_rules(fields))
    elif "permit" in raw_doc_type:
        violations.extend(validate_permit_rules(fields))

    # 5. Watchlist / Blacklist Check (Requirement 3)
    # -------------------------------------------------------------
    is_blacklisted, match_details = check_blacklist(doc_num, name, dob_str)
    if is_blacklisted:
        violations.append(
            Violation(
                field="watchlist_hit",
                rule_violated=f"Matched active law enforcement watchlist ({match_details.get('category')}): {match_details.get('reason')}",
                severity=Severity.CRITICAL.value,
            )
        )
        warnings.append(f"CRITICAL WATCHLIST HIT: {match_details.get('reason')}")
        details["blacklist_match"] = match_details

    # 6. Scoring Algorithm & Overall Validity (Requirement 5)
    # -------------------------------------------------------------
    score = 100.0
    for v in violations:
        sev = v.severity.upper()
        if sev == Severity.CRITICAL.value:
            score -= 40.0
        elif sev == Severity.HIGH.value:
            score -= 25.0
        elif sev == Severity.MEDIUM.value:
            score -= 15.0
        else:
            score -= 5.0

    if is_blacklisted:
        score = 0.0

    if is_expired and carries_expiry:
        score = min(score, 35.0)

    final_score = max(0.0, min(100.0, round(score, 1)))

    has_critical = any(v.severity == Severity.CRITICAL.value for v in violations)
    is_valid = (final_score >= 60.0) and not is_blacklisted and not (is_expired and carries_expiry) and not has_critical

    return ValidationResult(
        is_valid=is_valid,
        violations=violations,
        is_expired=bool(is_expired and carries_expiry),
        is_blacklisted=is_blacklisted,
        validation_score=final_score,
        document_type=raw_doc_type,
        document_number=doc_num,
        warnings=warnings,
        details=details,
        field_cross_validation=field_cross_validation,
        type_mismatch_warning=type_mismatch_warning,
    )
