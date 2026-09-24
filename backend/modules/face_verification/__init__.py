"""
Module 4: Face Verification & Morphing Attack Detection package
"""
from .engine import FaceVerificationEngineInterface, OpenCVFaceVerificationEngine, get_face_engine
from .schemas import FaceVerifyResult, BoundingBox, MorphDetectionResult, MorphSignalDetail
from .morph_detection import detect_morphing

__all__ = [
    "FaceVerificationEngineInterface",
    "OpenCVFaceVerificationEngine",
    "get_face_engine",
    "FaceVerifyResult",
    "BoundingBox",
    "MorphDetectionResult",
    "MorphSignalDetail",
    "detect_morphing"
]
