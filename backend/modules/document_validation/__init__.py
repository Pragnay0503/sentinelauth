"""
document_validation — Module 2: Document Validation Engine.
Performs rules-based document verification, logical consistency checks,
watchlist/blacklist lookups, and pulls forward Module 1 tamper/mismatch signals.
"""
from .schemas import Severity, ValidationResult, Violation
from .validator import validate_document
from .blacklist import check_blacklist

__all__ = [
    "Severity",
    "ValidationResult",
    "Violation",
    "validate_document",
    "check_blacklist",
]
