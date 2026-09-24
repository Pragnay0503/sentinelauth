"""
routes_audit.py - Audit trail and historical scan inspection endpoints.
Exposes:
  - GET /api/audit/scan/{id}
  - GET /api/audit/search
  - GET /api/audit/stats
  - GET /api/audit/image/{filename}
  - POST /api/audit/action
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..db.models import ScanRecord, AuditLog
from ..db.crud import get_scan_by_id, search_scans, get_dashboard_stats

router = APIRouter(prefix="/api/audit", tags=["Audit Trail"])

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")


class AuditActionRequest(BaseModel):
    scan_id: str
    officer_id: str
    action: str = Field(..., description="STATUS_OVERRIDE, NOTE_ADDED, MANUAL_PASS, MANUAL_REJECT")
    details: str
    new_status: Optional[str] = None


@router.get("/scan/{scan_id}", summary="Retrieve historical scan by ID")
async def get_scan_record_endpoint(scan_id: str, db: Session = Depends(get_db)):
    record = get_scan_by_id(db, scan_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Scan record '{scan_id}' not found.")
    
    # Include audit actions log
    actions = [
        {
            "id": a.id,
            "timestamp": a.timestamp.isoformat() + "Z",
            "officer_id": a.officer_id,
            "action": a.action,
            "details": a.details
        }
        for a in record.actions
    ]
    
    return {
        "id": record.id,
        "timestamp": record.timestamp.isoformat() + "Z",
        "document_type": record.document_type,
        "holder_name": record.holder_name,
        "document_number": record.document_number,
        "risk_score": record.risk_score,
        "risk_tier": record.risk_tier,
        "status": record.status,
        "validation_passed": record.validation_passed,
        "tampering_score": record.tampering_score,
        "face_match_confidence": record.face_match_confidence,
        "officer_id": record.officer_id,
        "checkpoint": record.checkpoint,
        "payload": record.payload,
        "actions": actions
    }


@router.get("/search", summary="Search historical scans with filters")
async def search_scans_endpoint(
    q: Optional[str] = Query(None, description="Search term across name, doc number, or scan ID"),
    risk_tier: Optional[str] = Query(None, description="Filter by tier: LOW, MEDIUM, HIGH, CRITICAL, ALL"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    flagged_only: bool = Query(False, description="Filter for high/critical risks only"),
    start_date: Optional[str] = Query(None, description="ISO format start date"),
    end_date: Optional[str] = Query(None, description="ISO format end date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    dt_start = None
    dt_end = None
    if start_date:
        try:
            dt_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except Exception:
            pass
    if end_date:
        try:
            dt_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except Exception:
            pass

    records, total = search_scans(
        db=db,
        query=q,
        risk_tier=risk_tier,
        document_type=document_type,
        flagged_only=flagged_only,
        start_date=dt_start,
        end_date=dt_end,
        skip=skip,
        limit=limit
    )

    items = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() + "Z",
            "document_type": r.document_type,
            "holder_name": r.holder_name,
            "document_number": r.document_number,
            "risk_score": r.risk_score,
            "risk_tier": r.risk_tier,
            "status": r.status,
            "validation_passed": r.validation_passed,
            "tampering_score": r.tampering_score,
            "face_match_confidence": r.face_match_confidence,
            "officer_id": r.officer_id,
            "checkpoint": r.checkpoint
        }
        for r in records
    ]

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": items
    }


@router.get("/stats", summary="Checkpoint screening metrics and statistics")
async def get_stats_endpoint(db: Session = Depends(get_db)):
    return get_dashboard_stats(db)


@router.get("/image/{filename}", summary="Retrieve stored document scan image")
async def get_scan_image_endpoint(filename: str):
    file_path = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(file_path)


@router.post("/action", summary="Append an officer note or status override to a scan record")
async def add_audit_action_endpoint(action_req: AuditActionRequest, db: Session = Depends(get_db)):
    record = get_scan_by_id(db, action_req.scan_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scan record not found.")

    if action_req.new_status:
        record.status = action_req.new_status

    log_entry = AuditLog(
        scan_id=record.id,
        officer_id=action_req.officer_id,
        action=action_req.action,
        details=action_req.details
    )
    db.add(log_entry)
    db.commit()
    db.refresh(record)

    return {"status": "ok", "message": "Audit action recorded successfully."}
