"""
schemas.py - Pydantic models for Risk Engine and Full Scan orchestration.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..modules.ocr_extraction.schemas import OCRResult
from ..modules.document_validation.schemas import ValidationResult
from ..modules.tampering_detection.schemas import TamperingResult
from ..modules.face_verification.schemas import FaceVerifyResult


class RiskFactor(BaseModel):
    category: str = Field(..., description="WATCHLIST, VALIDATION, TAMPERING, BIOMETRICS, FORMAT")
    title: str = Field(..., description="Short factor summary")
    description: str = Field(..., description="Detailed explanation of the risk signal")
    points_added: float = Field(..., description="Points contributed to total risk score")
    severity: str = Field(..., description="LOW, MEDIUM, HIGH, CRITICAL")


class RiskAssessment(BaseModel):
    risk_score: float = Field(..., ge=0.0, le=100.0, description="Final combined score 0-100")
    risk_tier: str = Field(..., description="LOW, MEDIUM, HIGH, CRITICAL")
    operational_action: str = Field(..., description="CLEAR, SECONDARY_INSPECTION, SUPERVISOR_REVIEW, INTERDICT_IMMEDIATE")
    recommendation: str = Field(..., description="Clear operational guidance for border security personnel")
    factors: List[RiskFactor] = Field(default_factory=list, description="Every positive contributing risk factor")
    clear_factors: List[str] = Field(default_factory=list, description="Evidence confirming document authenticity")


class FullScanReport(BaseModel):
    scan_id: str = Field(..., description="Unique persistent scan identifier")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    officer_id: str = Field("OFFICER-4819")
    checkpoint: str = Field("Delhi IGI Airport (T3 Arrival)")
    document_type: str
    holder_name: Optional[str] = None
    document_number: Optional[str] = None
    
    # Combined Risk
    risk: RiskAssessment
    
    # 4 Modules detailed reports
    ocr: OCRResult
    validation: ValidationResult
    tampering: TamperingResult
    biometrics: Optional[FaceVerifyResult] = None
    
    # Image references
    document_image_url: Optional[str] = None
    ela_heatmap_url: Optional[str] = None
    historical_check: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cross-scan historical check results comparing against past screenings of the same identity"
    )
