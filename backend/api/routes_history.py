"""
routes_history.py - REST API endpoints for Append-Only Screening History.

Exposes:
  - POST /api/history/screenings                   : Append a new screening record
  - POST /api/history/screenings/{id}/correct      : Append an immutable correction
  - GET  /api/history/screenings/{id}              : Retrieve screening and correction trail
  - GET  /api/history/screenings                   : Filterable search with indexed queries
  - GET  /api/history/repeat-identity              : Fast repeat-identity and anomaly lookup
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.screening_history import (
    ALLOWED_CHECK_RESULTS,
    ALLOWED_OUTCOMES,
    ScreeningHistoryRecord,
    check_repeat_identities,
    create_correction_record,
    create_screening_record,
    get_screening_record,
    search_screening_history,
)

router = APIRouter(prefix="/api/history", tags=["Screening History"])


class CheckDetail(BaseModel):
    status: str = Field(..., description="PASSED, FAILED, or NOT_EVALUATED")
    reason: str = Field("", description="Explanation or metric behind the check outcome")


class OutcomeTrigger(BaseModel):
    producing_check: Optional[str] = Field(None, description="Check name that determined the final outcome")
    producing_field: Optional[str] = Field(None, description="Field name identified by the producing check")


class CreateScreeningRequest(BaseModel):
    officer_id: str = Field(..., description="Badge or officer identifier")
    document_type: str = Field(..., description="Type of document (e.g. passport, visa, aadhaar)")
    document_number: str = Field(..., description="Document number (masked automatically upon storage)")
    name: Optional[str] = Field(None, description="Full name of document holder")
    dob: Optional[str] = Field(None, description="Date of birth (YYYY-MM-DD or DD/MM/YYYY)")
    nationality: Optional[str] = Field(None, description="ISO 3166-1 alpha-3 code (e.g. IND, GBR)")
    outcome: str = Field(..., description="VERIFIED, TAMPERED, EXPIRED, SKIPPED, or UNKNOWN")
    risk_score: float = Field(..., ge=0.0, le=100.0, description="Overall risk score (0-100)")
    checks: Dict[str, CheckDetail] = Field(
        default_factory=dict,
        description="Every check's result with PASSED/FAILED/NOT_EVALUATED status and reason",
    )
    outcome_trigger: Optional[OutcomeTrigger] = Field(
        None,
        description="Check and field that determined the outcome",
    )
    session_id: Optional[str] = Field(None, description="Session ID linking documents screened together")
    image_hash: Optional[str] = Field(None, description="SHA-256 digest of document image (never raw image)")
    processing_time_ms: float = Field(0.0, ge=0.0, description="Total inspection processing time in ms")
    screening_id: Optional[str] = Field(None, description="Optional custom or pre-generated screening ID")


class CorrectionRequest(BaseModel):
    corrected_by: str = Field(..., description="Officer ID or badge of who is making the correction")
    correction_reason: str = Field(..., min_length=5, description="Auditable justification for the correction")
    new_outcome: str = Field(..., description="Updated outcome: VERIFIED, TAMPERED, EXPIRED, SKIPPED, UNKNOWN")
    new_risk_score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Updated risk score")
    new_checks: Optional[Dict[str, CheckDetail]] = Field(None, description="Updated checks dictionary")
    outcome_trigger: Optional[OutcomeTrigger] = Field(None, description="Updated trigger check and field")


@router.post(
    "/screenings",
    status_code=status.HTTP_201_CREATED,
    summary="Append a new screening record to immutable history",
)
def append_screening_endpoint(
    req: CreateScreeningRequest,
    db: Session = Depends(get_db),
):
    """
    Append an immutable screening record.
    Never overwrites or deletes existing data.
    """
    norm_outcome = req.outcome.upper()
    if norm_outcome not in ALLOWED_OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid outcome '{req.outcome}'. Allowed: {sorted(list(ALLOWED_OUTCOMES))}",
        )

    # Convert checks to dict structure
    serialized_checks: Dict[str, Dict[str, str]] = {}
    for chk_name, chk_obj in req.checks.items():
        st = chk_obj.status.upper()
        if st not in ALLOWED_CHECK_RESULTS:
            st = "NOT_EVALUATED"
        serialized_checks[chk_name] = {"status": st, "reason": chk_obj.reason}

    producing_chk = req.outcome_trigger.producing_check if req.outcome_trigger else None
    producing_fld = req.outcome_trigger.producing_field if req.outcome_trigger else None

    record = create_screening_record(
        db,
        officer_id=req.officer_id,
        document_type=req.document_type,
        document_number=req.document_number,
        name=req.name,
        dob=req.dob,
        nationality=req.nationality,
        outcome=norm_outcome,
        risk_score=req.risk_score,
        checks=serialized_checks,
        producing_check=producing_chk,
        producing_field=producing_fld,
        session_id=req.session_id,
        image_hash=req.image_hash,
        processing_time_ms=req.processing_time_ms,
        screening_id=req.screening_id,
    )

    return {
        "success": True,
        "message": "Screening record appended successfully to immutable history.",
        "record": record.to_dict(include_corrections=True),
    }


@router.post(
    "/screenings/{screening_id}/correct",
    status_code=status.HTTP_201_CREATED,
    summary="Append an immutable correction linked to an existing screening",
)
def correct_screening_endpoint(
    screening_id: str,
    req: CorrectionRequest,
    db: Session = Depends(get_db),
):
    """
    Append a linked correction record.
    Preserves the original screening decision permanently while recording the officer's correction.
    """
    norm_outcome = req.new_outcome.upper()
    if norm_outcome not in ALLOWED_OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid new_outcome '{req.new_outcome}'. Allowed: {sorted(list(ALLOWED_OUTCOMES))}",
        )

    serialized_checks: Optional[Dict[str, Dict[str, str]]] = None
    if req.new_checks is not None:
        serialized_checks = {}
        for chk_name, chk_obj in req.new_checks.items():
            st = chk_obj.status.upper()
            if st not in ALLOWED_CHECK_RESULTS:
                st = "NOT_EVALUATED"
            serialized_checks[chk_name] = {"status": st, "reason": chk_obj.reason}

    producing_chk = req.outcome_trigger.producing_check if req.outcome_trigger else None
    producing_fld = req.outcome_trigger.producing_field if req.outcome_trigger else None

    try:
        correction = create_correction_record(
            db,
            original_screening_id=screening_id,
            corrected_by=req.corrected_by,
            correction_reason=req.correction_reason,
            new_outcome=norm_outcome,
            new_risk_score=req.new_risk_score,
            new_checks=serialized_checks,
            producing_check=producing_chk,
            producing_field=producing_fld,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return {
        "success": True,
        "message": "Correction appended successfully. Original decision remains permanent.",
        "correction": correction.to_dict(include_corrections=False),
    }


@router.get(
    "/screenings/{screening_id}",
    summary="Retrieve screening record with full immutable correction trail",
)
def get_screening_endpoint(
    screening_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve full screening details, including original decision and all corrections."""
    record = get_screening_record(db, screening_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screening record '{screening_id}' not found.",
        )
    return record.to_dict(include_corrections=True)


@router.get(
    "/screenings",
    summary="Search screening history with indexed filters",
)
def search_screenings_endpoint(
    document_number: Optional[str] = Query(None, description="Document number (masked or unmasked search)"),
    name: Optional[str] = Query(None, description="Holder name (searches composite index with DOB)"),
    dob: Optional[str] = Query(None, description="Date of birth (searches composite index with name)"),
    nationality: Optional[str] = Query(None, description="ISO alpha-3 code (e.g. IND)"),
    outcome: Optional[str] = Query(None, description="Outcome filter: VERIFIED, TAMPERED, EXPIRED, SKIPPED, UNKNOWN"),
    officer_id: Optional[str] = Query(None, description="Officer badge/identifier"),
    session_id: Optional[str] = Query(None, description="Linked session ID"),
    image_hash: Optional[str] = Query(None, description="SHA-256 hash of document image"),
    include_corrections_only: Optional[bool] = Query(None, description="Filter for corrections only"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Search historical screening records using database indexes for high throughput.
    """
    records, total_count = search_screening_history(
        db,
        document_number=document_number,
        name=name,
        dob=dob,
        nationality=nationality,
        outcome=outcome,
        officer_id=officer_id,
        session_id=session_id,
        image_hash=image_hash,
        include_corrections_only=include_corrections_only,
        limit=limit,
        offset=offset,
    )

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "results": [r.to_dict(include_corrections=True) for r in records],
    }


@router.get(
    "/repeat-identity",
    summary="Fast repeat-identity lookup and anomaly detection",
)
def repeat_identity_endpoint(
    name: Optional[str] = Query(None, description="Holder name"),
    dob: Optional[str] = Query(None, description="Holder date of birth (YYYY-MM-DD or DD/MM/YYYY)"),
    document_number: Optional[str] = Query(None, description="Document number to check for reuse across identities"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    High-speed repeat identity and document reuse detection leveraging:
    - Composite index (name, dob) for traveler crossing history
    - Document number index for cloned/reused document detection
    """
    if not name and not dob and not document_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one query parameter (name+dob or document_number) is required.",
        )

    results = check_repeat_identities(
        db,
        name=name,
        dob=dob,
        document_number=document_number,
        limit=limit,
    )
    return results
