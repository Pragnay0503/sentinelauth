"""
router.py - FastAPI router for POST /api/ocr/extract.
Fully self-contained (only imports from this module and FastAPI).
"""
from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .extractor import extract_ocr
from .ocr_engine import OCREngineFailure, get_ocr_readiness
from .schemas import DocumentType, OCRResult

router = APIRouter(prefix="/api/ocr", tags=["OCR Extraction"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}
_MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB


@router.post(
    "/extract",
    response_model=OCRResult,
    summary="Extract structured fields from a document image",
    description=(
        "Upload a passport, visa, national ID, driving license, or permit image. "
        "Returns structured OCR fields, per-field confidence scores, "
        "MRZ checksum validation result, and any field mismatches "
        "(MRZ vs visual) that indicate potential document tampering."
    ),
)
async def extract_document(
    file: UploadFile = File(..., description="Document image (JPEG/PNG/BMP/TIFF/WebP, max 15 MB)"),
    document_type: str = Form(..., description="One of: passport, visa, national_id, driving_license, permit, national_id_pan, national_id_aadhaar, national_id_voter"),
    back_image: Optional[UploadFile] = File(None, description="Optional back-side image of document"),
):
    # --- Validate document type ---
    try:
        doc_type = DocumentType(document_type.lower().strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid document_type '{document_type}'. "
                   f"Must be one of: {[e.value for e in DocumentType]}",
        )

    # --- Validate MIME type for front image ---
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{content_type}'. Supported: {sorted(_ALLOWED_TYPES)}",
        )

    # --- Read front image bytes ---
    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(image_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size {len(image_bytes)} bytes exceeds limit of {_MAX_FILE_SIZE} bytes (15 MB).",
        )

    # --- Read back image bytes if provided ---
    back_image_bytes: Optional[bytes] = None
    if back_image is not None and back_image.filename:
        back_content_type = (back_image.content_type or "").lower()
        if back_content_type and back_content_type not in _ALLOWED_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported media type for back image '{back_content_type}'. Supported: {sorted(_ALLOWED_TYPES)}",
            )
        back_bytes = await back_image.read()
        if len(back_bytes) > 0:
            if len(back_bytes) > _MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"Back image file size {len(back_bytes)} bytes exceeds limit of {_MAX_FILE_SIZE} bytes (15 MB).",
                )
            back_image_bytes = back_bytes

    # --- Run pipeline ---
    try:
        result: OCRResult = await run_in_threadpool(extract_ocr, image_bytes, doc_type.value, back_image_bytes)
    except OCREngineFailure as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "OCR extraction failed",
                "paddleocr_error": exc.paddleocr_error,
                "tesseract_error": exc.tesseract_error,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"OCR extraction failed: {exc}",
        )

    return result


@router.get("/health", summary="Health check for OCR module")
async def health():
    readiness = get_ocr_readiness()
    return {
        "status": "ok",
        "module": "ocr_extraction",
        "paddleocr_ready": readiness.get("paddleocr_ready", False),
        "tesseract_ready": readiness.get("tesseract_ready", False),
        "ocr_ready": readiness["ready"],
        "ocr_loading": readiness["loading"],
        "model_status": readiness.get("model_status", "ready"),
    }
