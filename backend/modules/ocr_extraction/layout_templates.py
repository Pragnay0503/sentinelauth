"""
layout_templates.py - Document layout templates for region-based OCR.

Defines percentage-based bounding boxes (ymin, xmin, ymax, xmax) for all supported
document types: passport, visa, national_id_pan, national_id_aadhaar, national_id_voter,
driving_license, permit.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple
import cv2
import numpy as np

# Bounding box format: (ymin, xmin, ymax, xmax) in normalized coordinates [0.0, 1.0]
RegionBBox = Tuple[float, float, float, float]

DOCUMENT_LAYOUT_TEMPLATES: Dict[str, Dict[str, RegionBBox]] = {
    "passport": {
        "mrz": (0.80, 0.00, 1.00, 1.00),             # Bottom 20% contains 2-line TD3 MRZ strip
        "passport_number": (0.07, 0.58, 0.24, 0.98), # Top-right document number
        "surname": (0.22, 0.20, 0.36, 0.85),
        "given_names": (0.33, 0.20, 0.48, 0.85),
        "nationality": (0.44, 0.20, 0.58, 0.60),
        "dob": (0.49, 0.20, 0.63, 0.65),
        "sex": (0.55, 0.20, 0.68, 0.50),
        "expiry": (0.66, 0.20, 0.82, 0.65),
    },
    "visa": {
        "mrz": (0.82, 0.00, 1.00, 1.00),             # Bottom strip if MRZ present
        "visa_number": (0.05, 0.55, 0.24, 0.98),
        "name": (0.20, 0.12, 0.42, 0.88),
        "passport_number": (0.38, 0.12, 0.55, 0.60),
        "valid_from": (0.50, 0.12, 0.66, 0.55),
        "expiry": (0.62, 0.12, 0.78, 0.55),
    },
    "national_id_pan": {
        "pan_number":  (0.16, 0.04, 0.30, 0.70),     # Permanent Account Number (10 alphanumeric chars)
        "name":        (0.31, 0.04, 0.47, 0.70),     # Cardholder Name
        "father_name": (0.48, 0.04, 0.64, 0.70),     # Father's Name
        "dob":         (0.65, 0.04, 0.81, 0.70),     # Date of Birth (DD/MM/YYYY)
    },
    "national_id_aadhaar": {
        "name":           (0.14, 0.04, 0.27, 0.55),   # Resident Name (left of portrait)
        "dob":            (0.28, 0.04, 0.39, 0.55),   # Date of Birth line (DOB: DD/MM/YYYY)
        "gender":         (0.40, 0.04, 0.51, 0.55),   # Gender (MALE / FEMALE)
        "address":        (0.52, 0.04, 0.68, 0.96),   # Full Address line
        "aadhaar_number": (0.70, 0.08, 0.88, 0.92),   # 12-digit UID band (4 4 4 digits)
    },
    "national_id_voter": {
        "epic_number": (0.15, 0.04, 0.27, 0.70),     # EPIC alphanumeric number
        "name":        (0.28, 0.04, 0.41, 0.70),     # Elector Name
        "father_name": (0.42, 0.04, 0.55, 0.70),     # Father's Name
        "gender":      (0.56, 0.04, 0.69, 0.35),     # Gender
        "dob":         (0.56, 0.35, 0.69, 0.70),     # Date of Birth (DD/MM/YYYY)
    },

    "driving_license": {
        "dl_number": (0.10, 0.20, 0.35, 0.95),       # DL Number
        "name": (0.26, 0.20, 0.48, 0.85),
        "dob": (0.45, 0.20, 0.64, 0.65),
        "expiry": (0.60, 0.20, 0.84, 0.75),
    },
    "permit": {
        "permit_number": (0.08, 0.35, 0.28, 0.95),
        "name": (0.25, 0.12, 0.45, 0.85),
        "valid_until": (0.50, 0.12, 0.75, 0.75),
    },
}


def get_layout_template(document_type: str) -> Optional[Dict[str, RegionBBox]]:
    """Retrieve bounding box layout for a document type."""
    doc_type_key = document_type.lower().strip()
    if doc_type_key in DOCUMENT_LAYOUT_TEMPLATES:
        return DOCUMENT_LAYOUT_TEMPLATES[doc_type_key]

    # Subtype aliases
    if doc_type_key in ("national_id", "national_id_aadhaar", "aadhaar"):
        return DOCUMENT_LAYOUT_TEMPLATES["national_id_aadhaar"]
    if doc_type_key in ("pan", "national_id_pan"):
        return DOCUMENT_LAYOUT_TEMPLATES["national_id_pan"]
    if doc_type_key in ("voter", "voter_id", "national_id_voter"):
        return DOCUMENT_LAYOUT_TEMPLATES["national_id_voter"]

    return None


def crop_region(
    img: np.ndarray,
    bbox: RegionBBox,
    padding: float = 0.02
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    Crop an image using a normalized bounding box (ymin, xmin, ymax, xmax)
    with optional margin padding. Returns the cropped patch and pixel coordinates (x1, y1, x2, y2).
    """
    h, w = img.shape[:2]
    ymin, xmin, ymax, xmax = bbox

    # Apply margin padding
    ymin_pad = max(0.0, ymin - padding)
    xmin_pad = max(0.0, xmin - padding)
    ymax_pad = min(1.0, ymax + padding)
    xmax_pad = min(1.0, xmax + padding)

    y1 = int(round(ymin_pad * h))
    y2 = min(h, max(y1 + 1, int(round(ymax_pad * h))))
    x1 = int(round(xmin_pad * w))
    x2 = min(w, max(x1 + 1, int(round(xmax_pad * w))))

    patch = img[y1:y2, x1:x2]
    return patch, (x1, y1, x2, y2)
