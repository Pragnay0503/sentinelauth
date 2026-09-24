"""
Module 3: Tampering Detection package
"""
from .detector import detect_tampering
from .schemas import (
    TamperingResult,
    ELAResult,
    EXIFResult,
    PhotoTamperingResult,
    TextConsistencyResult,
    StampCheckResult,
)

__all__ = [
    "detect_tampering",
    "TamperingResult",
    "ELAResult",
    "EXIFResult",
    "PhotoTamperingResult",
    "TextConsistencyResult",
    "StampCheckResult",
]
