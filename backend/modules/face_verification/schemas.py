"""
schemas.py - Pydantic models for Module 4: Biometric Face Verification & Morphing Attack Detection.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: int = Field(..., description="Top-left X coordinate")
    y: int = Field(..., description="Top-left Y coordinate")
    width: int = Field(..., description="Box width")
    height: int = Field(..., description="Box height")


class MorphSignalDetail(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized signal risk/anomaly score (0.0 - 1.0)")
    flagged: bool = Field(..., description="Whether this individual heuristic signal breached its risk threshold")
    description: str = Field(..., description="Human-readable forensic rationale for this signal")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Raw mathematical/forensic measurements")


class MorphDetectionResult(BaseModel):
    """
    Result of Single-Image Morphing Attack Detection (S-MAD) on the document photo.
    Evaluates 4 explainable heuristic signals: LBP texture, facial symmetry, double-edge ghosting,
    and frequency-domain discontinuities.
    """
    face_detected: bool = Field(True, description="Whether a face was detected on the document photo")
    morph_suspicion_score: float = Field(0.0, ge=0.0, le=1.0, description="Combined suspicion score 0.0 (clean) to 1.0 (high morph risk)")
    suspicion_tier: str = Field("NORMAL", description="NORMAL (<0.35), ELEVATED (0.35-0.55), HIGH_SUSPICION (>0.55)")
    is_morph_suspected: bool = Field(False, description="Whether the suspicion score exceeds threshold (>=0.35)")
    morph_flags: List[str] = Field(default_factory=list, description="Specific heuristic flags triggered")
    signals: Dict[str, MorphSignalDetail] = Field(default_factory=dict, description="Detailed breakdown of each of the 4 detection signals")
    summary: str = Field("Document photo verified: authentic single-identity micro-texture and coherent geometry.")
    method: str = Field("Single-Image Heuristic S-MAD (Texture, Symmetry, Ghost Contours, Spectral FFT)")


class FaceVerifyResult(BaseModel):
    match: bool = Field(..., description="Whether the faces match according to the threshold")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Normalized match confidence (0.0 to 1.0)")
    cosine_similarity: float = Field(..., description="Raw SFace cosine similarity (-1.0 to 1.0)")
    l2_distance: float = Field(..., description="L2 euclidean distance between 128-d embeddings")
    threshold_applied: float = Field(..., description="Cosine threshold used for classification")
    
    status: str = Field("SUCCESS", description="SUCCESS, NO_FACE_IN_DOCUMENT, NO_FACE_IN_SELFIE, MULTIPLE_FACES")
    message: str = Field("Face verification completed successfully.")
    
    doc_face_box: Optional[BoundingBox] = None
    selfie_face_box: Optional[BoundingBox] = None
    doc_face_count: int = Field(1, description="Number of faces detected on the document")
    selfie_face_count: int = Field(1, description="Number of faces detected on the selfie")

    # Extension: S-MAD Face Morphing Attack Detection (Document Photo Only)
    morph_analysis: Optional[MorphDetectionResult] = Field(
        default=None,
        description="Single-Image Morphing Attack Detection (S-MAD) analysis run on the document photo"
    )
