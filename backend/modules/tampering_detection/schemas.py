"""
schemas.py - Pydantic models for Module 3: Tampering Detection.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ELAResult(BaseModel):
    anomaly_score: float = Field(..., ge=0.0, le=1.0, description="Normalized ELA anomaly score 0-1")
    mean_error: float = Field(..., description="Mean compression diff across all pixels")
    max_error: float = Field(..., description="Peak compression diff")
    heatmap_b64: str = Field(..., description="Base64-encoded JPEG image of ELA heatmap")
    flagged: bool = Field(..., description="True if compression anomalies exceed standard threshold")


class EXIFResult(BaseModel):
    has_exif: bool = Field(..., description="Whether EXIF metadata was present")
    software_detected: Optional[str] = Field(None, description="Software tag found (e.g. Photoshop, Canva)")
    editing_tools_found: List[str] = Field(default_factory=list, description="List of suspicious editing tools identified")
    is_suspicious: bool = Field(False, description="True if editing software or stripped EXIF flagged")
    metadata_dump: Dict[str, str] = Field(default_factory=dict, description="Safe key metadata properties")


class PhotoTamperingResult(BaseModel):
    photo_detected: bool = Field(..., description="True if face photo region was located")
    noise_variance_ratio: float = Field(..., description="Ratio of face region noise to document texture noise")
    ela_divergence: float = Field(..., description="Difference between photo ELA error and document ELA error")
    photo_splicing_detected: bool = Field(False, description="True if photo replacement/splicing markers found")
    confidence: float = Field(..., ge=0.0, le=1.0)


class TextConsistencyResult(BaseModel):
    text_line_count: int = Field(..., description="Number of text lines evaluated")
    font_size_variance: float = Field(..., description="Variance in text line heights across document")
    baseline_alignment_variance: float = Field(..., description="Variance in text baseline angles")
    text_manipulation_suspected: bool = Field(False, description="True if inconsistent font metrics/spacing found")
    confidence: float = Field(..., ge=0.0, le=1.0)


class StampCheckResult(BaseModel):
    stamp_detected: bool = Field(..., description="True if official emblem/seal region was identified")
    match_score: float = Field(..., ge=0.0, le=1.0, description="Emblem feature/template matching score")
    edge_regularity: float = Field(..., ge=0.0, le=1.0, description="Contour edge smoothness and sharpness")
    forgery_suspected: bool = Field(False, description="True if stamp match score is low or irregular")


class FieldForensicsResult(BaseModel):
    ela_anomaly_score: float = Field(..., ge=0.0, le=1.0, description="Localized ELA divergence against peer baseline")
    font_consistency_score: float = Field(..., ge=0.0, le=1.0, description="Typography and baseline alignment similarity")
    likely_tampered: bool = Field(..., description="True if localized forensic signals indicate digital editing")
    crop_ela_heatmap_b64: str = Field(..., description="Base64 encoded JPEG of localized ELA heatmap crop")
    details: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Diagnostic metrics for field analysis")


class TamperingResult(BaseModel):
    tampering_score: float = Field(..., ge=0.0, le=1.0, description="Combined tampering risk score 0.0 to 1.0")
    is_tampered: bool = Field(..., description="True if tampering_score exceeds operational alert threshold (0.45)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence of forensics assessment")
    
    # Per-check breakdown
    ela: ELAResult
    exif: EXIFResult
    photo_region: PhotoTamperingResult
    text_consistency: TextConsistencyResult
    stamp_seal: StampCheckResult
    field_forensics: Dict[str, FieldForensicsResult] = Field(
        default_factory=dict,
        description="Localized forensics for individual high-risk fields"
    )
    
    flagged_checks: List[str] = Field(
        default_factory=list,
        description="List of specific forensic checks that fired (e.g. ['ELA_HIGH_ERROR', 'EDITING_SOFTWARE_DETECTED'])"
    )
    explanation: List[str] = Field(
        default_factory=list,
        description="Officer-facing forensic findings and evidence summary"
    )
    module_contributions: Dict[str, float] = Field(
        default_factory=dict,
        description="Individual forensic module score contributions"
    )
    outcome: Optional[str] = Field(
        None,
        description="Document verification outcome: TAMPERED, EXPIRED, VERIFIED, or SKIPPED"
    )
    outcome_reason: Optional[str] = Field(
        None,
        description="Plain-language reason naming the specific field"
    )
    mrz_cross_check: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Detailed MRZ vs Printed cross-check results"
    )

