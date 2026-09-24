"""
router.py — FastAPI endpoints for Document Validation (Module 2).
Exposes POST /api/validation/validate
"""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, HTTPException

from .schemas import ValidationResult
from .validator import validate_document

router = APIRouter(prefix="/api/validation", tags=["Document Validation"])


@router.post("/validate", response_model=ValidationResult)
async def validate_ocr_result(payload: Dict[str, Any]):
    """
    Validate an OCR extraction result against document rules,
    date consistency, watchlist databases, and tampering signals.
    """
    try:
        result = validate_document(payload)
        return result
    except Exception as err:
        raise HTTPException(
            status_code=400,
            detail=f"Document validation failed: {str(err)}"
        )
