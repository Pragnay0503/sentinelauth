"""
schemas.py — Pydantic input/output models for the OCR Extraction module.
Fully self-contained; imports only from pydantic and Python stdlib.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    auto                = "auto"
    unknown             = "unknown"
    passport            = "passport"
    visa                = "visa"
    national_id         = "national_id"
    driving_license     = "driving_license"
    permit              = "permit"
    national_id_pan     = "national_id_pan"
    national_id_aadhaar = "national_id_aadhaar"
    national_id_voter   = "national_id_voter"


class FieldSource(str, Enum):
    mrz    = "mrz"
    visual = "visual"
    both   = "both"


# ---------------------------------------------------------------------------
# Per-field result
# ---------------------------------------------------------------------------

class FieldResult(BaseModel):
    """Result for a single extracted document field."""
    value:      str         = Field(...,  description="Extracted text value")
    confidence: float       = Field(...,  ge=0.0, le=1.0,
                                    description="Confidence score 0-1")
    source:     FieldSource = Field(...,  description="Where the value came from")
    mismatch:   bool        = Field(False, description="MRZ vs visual value mismatch flag")


# ---------------------------------------------------------------------------
# Full OCR result (output schema)
# ---------------------------------------------------------------------------

class OCRResult(BaseModel):
    """Complete result returned by the OCR extraction endpoint."""

    document_type: DocumentType = Field(
        ..., description="Type of document processed"
    )

    detected_document_subtype: Optional[str] = Field(
        None,
        description="Auto-detected document subtype based on OCR anchor phrases",
    )

    document_type_mismatch: bool = Field(
        False,
        description="True if auto-detected document type conflicts with user-submitted type",
    )

    type_mismatch_warning: Optional[str] = Field(
        None,
        description="Human-readable warning when detected type differs from selected tab type",
    )

    submitted_document_type: Optional[str] = Field(
        None,
        description="User-submitted or selected tab document type",
    )

    extracted_fields: Dict[str, FieldResult] = Field(
        default_factory=dict,
        description="All extracted structured fields keyed by field name",
    )

    confidence_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Convenience flat map of field_name -> confidence (0-1)",
    )

    checksum_validation: Dict[str, Optional[bool]] = Field(
        default_factory=dict,
        description="Format and checksum results (e.g. aadhaar_verhoeff_valid, pan_format_valid)",
    )

    mrz_applicable: bool = Field(
        False,
        description="True if document type uses an MRZ zone (passport, visa); False otherwise",
    )

    mrz_validation_passed: Optional[bool] = Field(
        None,
        description="True if MRZ checksums passed; None if MRZ is not applicable to this document",
    )

    low_confidence_but_format_valid: bool = Field(
        False,
        description="True if regex/checksum validation passed but OCR confidence score was below 0.6",
    )

    field_mismatches: List[str] = Field(
        default_factory=list,
        description=(
            "Field names where MRZ-extracted value differs from visual-OCR value. "
            "Non-empty list is an early tampering signal."
        ),
    )

    visual_fields: Dict[str, str] = Field(
        default_factory=dict,
        description="Raw visual printed zone field extractions prior to MRZ reconciliation",
    )

    mrz_parsed: Optional[Dict[str, Any]] = Field(
        None,
        description="Parsed ICAO 9303 MRZ fields (surname, given_names, doc_number, dob, sex, expiry, nationality)",
    )

    mrz_checksums: Dict[str, bool] = Field(
        default_factory=dict,
        description="Per-field ICAO 9303 checksum validation results (doc_number, dob, expiry, composite)",
    )

    raw_ocr_text: str = Field(
        "",
        description="Full concatenated raw OCR text from the image",
    )

    processing_notes: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings and informational messages from the pipeline",
    )

    name_debug_info: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Diagnostics on candidate lines considered for person name field",
    )

    timing_stats: Dict[str, float] = Field(
        default_factory=dict,
        description="Execution time breakdown in milliseconds (load/resize, preprocessing, region OCR, MRZ, total)",
    )


class DocumentImage(BaseModel):
    """Input schema representing an image (bytes or file path) and document type."""
    image: bytes | str = Field(..., description="Raw image bytes or path to the image file")
    document_type: DocumentType = Field(..., description="Type of document")
    back_image: Optional[bytes | str] = Field(None, description="Optional raw image bytes or path to the back image file")

    model_config = {"arbitrary_types_allowed": True}


class ExtractionRequest(BaseModel):
    """For programmatic (non-multipart) use - accepts base64 image."""
    image_b64:     str
    document_type: DocumentType
