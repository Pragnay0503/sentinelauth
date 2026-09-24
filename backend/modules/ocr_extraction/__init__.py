"""OCR Extraction module — public surface."""
from .extractor import extract_ocr
from .schemas import DocumentType, DocumentImage, OCRResult, FieldResult, FieldSource
from .checksums import (
    validate_verhoeff,
    validate_aadhaar_number,
    is_masked_aadhaar,
    validate_pan_format,
    decode_pan_details,
    validate_epic_format,
)
from .field_extractor import (
    detect_document_subtype,
    CARRIED_FIELDS_BY_DOC_TYPE,
    DOC_TYPE_DISPLAY_NAMES,
)

__all__ = [
    "extract_ocr",
    "DocumentType",
    "DocumentImage",
    "OCRResult",
    "FieldResult",
    "FieldSource",
    "validate_verhoeff",
    "validate_aadhaar_number",
    "is_masked_aadhaar",
    "validate_pan_format",
    "decode_pan_details",
    "validate_epic_format",
    "detect_document_subtype",
    "CARRIED_FIELDS_BY_DOC_TYPE",
    "DOC_TYPE_DISPLAY_NAMES",
]

