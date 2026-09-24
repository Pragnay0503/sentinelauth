"""
schemas.py — Pydantic models for Document Validation (Module 2).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    WARNING = "WARNING"


class Violation(BaseModel):
    field: str = Field(..., description="Field name associated with violation or rule check")
    rule_violated: str = Field(..., description="Description of the rule that was violated")
    severity: str = Field(..., description="Severity level: CRITICAL, HIGH, MEDIUM, LOW, WARNING")


class FieldCrossValidationItem(BaseModel):
    visual_value: Optional[str] = Field(None, description="Printed visual OCR value")
    mrz_value: Optional[str] = Field(None, description="Normalized MRZ value")
    match: bool = Field(..., description="True if visual and MRZ fields agree")
    mrz_checksum_valid: Optional[bool] = Field(None, description="True if per-field MRZ check digit passed")
    flag: Optional[str] = Field(None, description="Alert flag: VISUAL_MRZ_MISMATCH, MRZ_CHECKSUM_INVALID, etc.")


class ValidationResult(BaseModel):
    """Complete output schema for Module 2 Document Validation."""
    is_valid: bool = Field(..., description="Overall validity flag (False if any critical violations, expired, or blacklisted)")
    violations: List[Violation] = Field(default_factory=list, description="List of detected rule violations")
    is_expired: bool = Field(False, description="True if document expiry date is in the past")
    is_blacklisted: bool = Field(False, description="True if document number, name, or DOB matches watchlist")
    validation_score: float = Field(..., ge=0.0, le=100.0, description="Overall validity score from 0 to 100")
    document_type: Optional[str] = Field(None, description="Document type validated")
    document_number: Optional[str] = Field(None, description="Document identifier extracted")
    warnings: List[str] = Field(default_factory=list, description="Summary warnings for human border officer")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed breakdown of validation checks")
    field_cross_validation: Dict[str, FieldCrossValidationItem] = Field(
        default_factory=dict,
        description="Per-field comparison between printed visual text and MRZ"
    )
    type_mismatch_warning: Optional[str] = Field(
        None,
        description="Human-readable warning when detected type differs from selected tab type"
    )
