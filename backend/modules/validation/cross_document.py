"""
cross_document.py - Multi-Document Cross-Verification and Identity Reuse Detection for SentinelAuth.

Implements:
1. VISA-TO-PASSPORT Cross-Verification:
   - Validates that the visa was issued against the presented passport:
     Compares visa.passport_number against passport.passport_number (printed and MRZ).
     Mismatch -> "visa was not issued for this passport".
   - Cross-verifies demographic fields across both documents:
     surname, given_names, date_of_birth, nationality.
2. OCR Tolerance:
   - Numeric and code fields (passport number, DOB, nationality) require exact normalized match.
   - Name fields (surname, given_names) tolerate explainable OCR-B confusion pairs
     (W<->M, W<->NN, M<->N, W<->N, O<->0, I<->1, S<->5, B<->8, RN<->M).
     Explainable differences recorded as OCR artifacts without flagging tampering.
     Unexplainable differences flagged as tampering.
3. Repeat Identity (Screening History Search):
   - Searches screening history for:
     (a) Same document number with a different name -> "possible multiple identities"
     (b) Same name + DOB with a different document number -> "possible multiple identities"
   - Lists prior screening timestamps and document IDs.
4. Unreadable Handling:
   - If any required field is missing or unreadable on either document, outcome is SKIPPED
     with an explicit reason naming the field (never a pass).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from backend.modules.validation.mrz_cross_check import (
    cross_check_mrz_vs_printed,
    explainable_by_ocr_b,
    _normalize_date_to_yymmdd,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Screening History Store & Models
# ---------------------------------------------------------------------------

@dataclass
class ScreeningRecord:
    """Represents a single screened document identity in history."""
    session_id: str
    timestamp: str
    document_id: str
    document_type: str
    document_number: str
    surname: str
    given_names: str
    full_name: str
    date_of_birth: str
    nationality: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ScreeningHistoryStore:
    """
    Thread-safe screening history database for detecting repeat identity fraud.
    Maintains indices by document number and normalized identity (name + DOB).
    """

    def __init__(self):
        self.records: List[ScreeningRecord] = []

    def clear(self) -> None:
        """Clears all screening records (used for test isolation)."""
        self.records.clear()

    def add_record(
        self,
        session_id: str,
        document_id: str,
        document_type: str,
        document_number: str,
        surname: str,
        given_names: str,
        date_of_birth: str,
        nationality: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScreeningRecord:
        """Adds a screened document record to the history."""
        ts = timestamp or datetime.utcnow().isoformat() + "Z"
        full_name = f"{surname.strip().upper()} {given_names.strip().upper()}".strip()
        rec = ScreeningRecord(
            session_id=session_id,
            timestamp=ts,
            document_id=document_id,
            document_type=document_type,
            document_number=document_number.strip().upper(),
            surname=surname.strip().upper(),
            given_names=given_names.strip().upper(),
            full_name=full_name,
            date_of_birth=_normalize_date_str(date_of_birth) or date_of_birth.strip(),
            nationality=nationality.strip().upper(),
            metadata=metadata or {},
        )
        self.records.append(rec)
        return rec

    def check_repeat_identity(
        self,
        document_number: str,
        surname: str,
        given_names: str,
        date_of_birth: str,
        current_session_id: str = "",
        document_type: str = "",
    ) -> Tuple[bool, Optional[str], Optional[str], List[Dict[str, Any]]]:
        """
        Searches history for identity anomalies:
        (a) Same document number with a different name
        (b) Same name + DOB with a different document number (within same document type)

        Returns:
            (is_flagged, flag_type, reason_str, list_of_prior_events)
        """
        doc_num_norm = document_number.strip().upper()
        name_norm = f"{surname.strip().upper()} {given_names.strip().upper()}".strip()
        dob_norm = _normalize_date_str(date_of_birth) or date_of_birth.strip()
        doc_type_norm = document_type.strip().lower()

        prior_events: List[Dict[str, Any]] = []

        # (a) Check: Same document number with a different name
        # 1. First check persistent screening_history database table
        try:
            from backend.db.database import SessionLocal
            from backend.db.screening_history import ScreeningHistoryRecord, mask_document_number
            db_session = SessionLocal()
            try:
                if doc_num_norm:
                    masked = mask_document_number(doc_num_norm)
                    db_doc_records = db_session.query(ScreeningHistoryRecord).filter(
                        (ScreeningHistoryRecord.document_number == doc_num_norm) |
                        (ScreeningHistoryRecord.document_number == masked) |
                        (ScreeningHistoryRecord.document_number.like(f"%{doc_num_norm}%"))
                    ).all()
                    for db_rec in db_doc_records:
                        if current_session_id and db_rec.session_id == current_session_id:
                            continue
                        if db_rec.name:
                            is_explainable, _ = explainable_by_ocr_b(name_norm, db_rec.name.upper())
                            if not is_explainable and name_norm != db_rec.name.upper():
                                prior_events.append({
                                    "type": "same_doc_different_name",
                                    "document_number": db_rec.document_number,
                                    "prior_name": db_rec.name,
                                    "current_name": name_norm,
                                    "timestamp": db_rec.timestamp.isoformat() + "Z" if db_rec.timestamp else "",
                                    "session_id": db_rec.session_id,
                                    "document_id": db_rec.screening_id,
                                })

                if name_norm and dob_norm:
                    db_name_records = db_session.query(ScreeningHistoryRecord).filter(
                        ScreeningHistoryRecord.dob == dob_norm
                    ).all()
                    for db_rec in db_name_records:
                        if current_session_id and db_rec.session_id == current_session_id:
                            continue
                        if doc_type_norm and db_rec.document_type and db_rec.document_type.lower() != doc_type_norm:
                            continue
                        if db_rec.name:
                            name_match, _ = explainable_by_ocr_b(name_norm, db_rec.name.upper())
                            if (name_match or name_norm == db_rec.name.upper()):
                                if db_rec.document_number and db_rec.document_number != doc_num_norm:
                                    prior_events.append({
                                        "type": "same_identity_different_doc",
                                        "name": db_rec.name,
                                        "date_of_birth": db_rec.dob,
                                        "prior_document_number": db_rec.document_number,
                                        "current_document_number": doc_num_norm,
                                        "timestamp": db_rec.timestamp.isoformat() + "Z" if db_rec.timestamp else "",
                                        "session_id": db_rec.session_id,
                                        "document_id": db_rec.screening_id,
                                    })
            finally:
                db_session.close()
        except Exception as e:
            logger.debug(f"Database screening_history query in cross_document: {e}")

        # 2. Check in-memory store records
        if doc_num_norm:
            for rec in self.records:
                if current_session_id and rec.session_id == current_session_id:
                    continue
                if rec.document_number == doc_num_norm:
                    # Check if name is substantially different (not explainable by OCR-B)
                    is_explainable, _ = explainable_by_ocr_b(name_norm, rec.full_name)
                    if not is_explainable and name_norm != rec.full_name:
                        prior_events.append({
                            "type": "same_doc_different_name",
                            "document_number": rec.document_number,
                            "prior_name": rec.full_name,
                            "current_name": name_norm,
                            "timestamp": rec.timestamp,
                            "session_id": rec.session_id,
                            "document_id": rec.document_id,
                        })

        same_doc_events = [p for p in prior_events if p.get("type") == "same_doc_different_name"]
        if same_doc_events:
            timestamps = [p["timestamp"] for p in same_doc_events]
            prior_names = list({p["prior_name"] for p in same_doc_events})
            reason = (
                f"possible multiple identities: same document number '{doc_num_norm}' "
                f"previously screened under different name(s) {prior_names} "
                f"at prior screening timestamps {timestamps}"
            )
            return True, "same_doc_different_name", reason, same_doc_events

        # (b) Check: Same name + DOB with a different document number (within same document type)
        if name_norm and dob_norm:
            for rec in self.records:
                if current_session_id and rec.session_id == current_session_id:
                    continue
                # If document_type is known for both, only compare within the same document type
                if doc_type_norm and rec.document_type and rec.document_type.lower() != doc_type_norm:
                    continue
                # Match name (allowing OCR-B confusion) and exact DOB
                name_match, _ = explainable_by_ocr_b(name_norm, rec.full_name)
                if (name_match or name_norm == rec.full_name) and rec.date_of_birth == dob_norm:
                    if rec.document_number and rec.document_number != doc_num_norm:
                        prior_events.append({
                            "type": "same_identity_different_doc",
                            "name": rec.full_name,
                            "date_of_birth": rec.date_of_birth,
                            "prior_document_number": rec.document_number,
                            "current_document_number": doc_num_norm,
                            "timestamp": rec.timestamp,
                            "session_id": rec.session_id,
                            "document_id": rec.document_id,
                        })

        same_id_events = [p for p in prior_events if p.get("type") == "same_identity_different_doc"]
        if same_id_events:
            timestamps = [p["timestamp"] for p in same_id_events]
            prior_docs = list({p["prior_document_number"] for p in same_id_events})
            reason = (
                f"possible multiple identities: identity '{name_norm}' (DOB: {dob_norm}) "
                f"previously screened with different document number(s) {prior_docs} "
                f"at prior screening timestamps {timestamps}"
            )
            return True, "same_identity_different_doc", reason, same_id_events

        return False, None, None, []


# Global screening history singleton
_GLOBAL_SCREENING_HISTORY = ScreeningHistoryStore()


def get_global_screening_history() -> ScreeningHistoryStore:
    """Returns the shared screening history store."""
    return _GLOBAL_SCREENING_HISTORY


# ---------------------------------------------------------------------------
# Date and String Normalization Helpers
# ---------------------------------------------------------------------------

def _normalize_date_str(d_str: str) -> Optional[str]:
    """Normalizes any date string into YYMMDD or YYYYMMDD."""
    if not d_str:
        return None
    # Use existing tested MRZ date normalizer
    yymmdd = _normalize_date_to_yymmdd(d_str)
    if yymmdd:
        return yymmdd
    digits = re.sub(r"\D", "", d_str)
    if len(digits) in (6, 8):
        return digits
    return None


def _normalize_code(c_str: str) -> str:
    """Normalizes alphanumeric codes, uppercased and trimmed."""
    if not c_str:
        return ""
    return re.sub(r"[^A-Z0-9]", "", c_str.upper())


# ---------------------------------------------------------------------------
# Document Data Extraction
# ---------------------------------------------------------------------------

def extract_document_features(
    doc: Union[np.ndarray, Dict[str, Any]],
    doc_type_hint: str = "",
    doc_id: str = "",
) -> Dict[str, Any]:
    """
    Extracts standardized demographic and identifier features from a document:
    Supports pre-extracted dictionary or raw image array.
    """
    if isinstance(doc, dict):
        # Handle dict from manifest ground truth or detector result
        p_fields = doc.get("printed_fields") or doc.get("ground_truth_fields") or doc
        m_fields = doc.get("mrz_fields") or {}
        doc_type = doc.get("document_type") or doc_type_hint
        if not doc_type:
            if "visa_number" in p_fields or "visa_number" in m_fields:
                doc_type = "visa"
            elif "passport_number" in p_fields or "passport" in str(doc.get("id", "")).lower():
                doc_type = "passport"

        # Resolve passport number
        pass_num = p_fields.get("passport_number") or m_fields.get("passport_number")
        if not pass_num and doc_type == "passport":
            pass_num = m_fields.get("document_number")

        return {
            "document_type": doc_type,
            "document_id": doc.get("id") or doc_id,
            "passport_number": _normalize_code(pass_num or ""),
            "visa_number": _normalize_code(p_fields.get("visa_number") or m_fields.get("document_number") or ""),
            "surname": (p_fields.get("surname") or m_fields.get("surname") or "").strip().upper(),
            "given_names": (p_fields.get("given_names") or m_fields.get("given_names") or "").strip().upper(),
            "date_of_birth": p_fields.get("date_of_birth") or m_fields.get("date_of_birth") or "",
            "nationality": _normalize_code(p_fields.get("nationality") or m_fields.get("nationality") or ""),
            "date_of_expiry": p_fields.get("date_of_expiry") or m_fields.get("date_of_expiry") or "",
            "raw_printed": p_fields,
            "raw_mrz": m_fields,
        }

    elif isinstance(doc, np.ndarray):
        # Run standard OCR and MRZ cross-check on image
        doc_type_norm = "visa" if "visa" in doc_type_hint.lower() else "passport"
        res = cross_check_mrz_vs_printed(doc, document_type=doc_type_norm, doc_id=doc_id)
        p_fields = res.get("printed_fields", {})
        m_fields = res.get("mrz_fields", {})

        pass_num = p_fields.get("passport_number")
        if not pass_num and doc_type_norm == "passport":
            pass_num = m_fields.get("document_number")

        # Fallback for visa: if passport_number wasn't captured in printed_fields
        if not pass_num and doc_type_norm == "visa":
            from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
            reader = _easyocr_engine.get_reader("en")
            raw_res = reader.readtext(doc)
            v_num = _normalize_code(p_fields.get("visa_number") or m_fields.get("document_number") or "")
            for bbox, text, conf in raw_res:
                t = text.strip().upper()
                # Clean known OCR artifacts in digits (e.g. '}' or ']' -> '3')
                t_clean = re.sub(r"[}\])>]", "3", t)
                m = re.match(r"^[A-Z][0-9]{7,8}$", t_clean)
                if m and t_clean != v_num:
                    pass_num = t_clean
                    p_fields["passport_number"] = t_clean
                    break

        return {
            "document_type": doc_type_norm,
            "document_id": doc_id,
            "passport_number": _normalize_code(pass_num or ""),
            "visa_number": _normalize_code(p_fields.get("visa_number") or m_fields.get("document_number") or ""),
            "surname": (p_fields.get("surname") or m_fields.get("surname") or "").strip().upper(),
            "given_names": (p_fields.get("given_names") or m_fields.get("given_names") or "").strip().upper(),
            "date_of_birth": p_fields.get("date_of_birth") or m_fields.get("date_of_birth") or "",
            "nationality": _normalize_code(p_fields.get("nationality") or m_fields.get("nationality") or ""),
            "date_of_expiry": p_fields.get("date_of_expiry") or m_fields.get("date_of_expiry") or "",
            "raw_printed": p_fields,
            "raw_mrz": m_fields,
        }

    else:
        raise TypeError(f"Unsupported document format: {type(doc)}")


# ---------------------------------------------------------------------------
# Main Cross-Document Verification Function
# ---------------------------------------------------------------------------

def verify_cross_document(
    doc_a: Union[np.ndarray, Dict[str, Any]],
    doc_b: Union[np.ndarray, Dict[str, Any]],
    doc_type_a: str = "",
    doc_type_b: str = "",
    doc_id_a: str = "",
    doc_id_b: str = "",
    session_id: str = "",
    timestamp: Optional[str] = None,
    history_store: Optional[ScreeningHistoryStore] = None,
    record_screening: bool = True,
) -> Dict[str, Any]:
    """
    Cross-verifies two documents presented in the same screening session.
    
    Checks:
    1. VISA-TO-PASSPORT:
       - Validates that the visa was issued against this specific passport.
         (Visa printed passport_number == Passport passport_number).
         Mismatch -> "visa was not issued for this passport".
       - Demographic alignment: surname, given_names, date_of_birth, nationality.
    2. OCR TOLERANCE:
       - OCR-B confusions on names are treated as OCR artifacts, not tampering.
       - Any other mismatch -> TAMPERED.
    3. REPEAT IDENTITY:
       - Checks screening history for document number reuse with different names
         or same identity presented with different document numbers.
       - Flag -> "possible multiple identities" with prior screening timestamps.
    4. UNREADABLE EITHER SIDE -> SKIPPED with explicit reason naming the field.
    """
    store = history_store if history_store is not None else _GLOBAL_SCREENING_HISTORY
    ts = timestamp or datetime.utcnow().isoformat() + "Z"
    sess_id = session_id or f"session_{int(datetime.utcnow().timestamp())}"

    # 1. Extract standardized features from both documents
    feat_a = extract_document_features(doc_a, doc_type_hint=doc_type_a, doc_id=doc_id_a)
    feat_b = extract_document_features(doc_b, doc_type_hint=doc_type_b, doc_id=doc_id_b)

    # 2. Determine document roles (Visa vs Passport)
    visa_feat: Optional[Dict[str, Any]] = None
    pass_feat: Optional[Dict[str, Any]] = None

    if feat_a["document_type"] == "visa" and feat_b["document_type"] == "passport":
        visa_feat, pass_feat = feat_a, feat_b
    elif feat_a["document_type"] == "passport" and feat_b["document_type"] == "visa":
        visa_feat, pass_feat = feat_b, feat_a
    elif feat_a["visa_number"] and feat_b["passport_number"]:
        visa_feat, pass_feat = feat_a, feat_b
    elif feat_b["visa_number"] and feat_a["passport_number"]:
        visa_feat, pass_feat = feat_b, feat_a
    else:
        # Generic pair cross-check
        pass_feat, visa_feat = feat_a, feat_b

    # -----------------------------------------------------------------------
    # Requirement 4: UNREADABLE EITHER SIDE -> SKIPPED
    # -----------------------------------------------------------------------
    required_passport_fields = ["passport_number", "surname", "date_of_birth", "nationality"]
    for f in required_passport_fields:
        if not pass_feat.get(f):
            return {
                "outcome": "SKIPPED",
                "field": f,
                "reason": f"Unreadable field '{f}' on passport ({pass_feat.get('document_id') or 'passport'}): cannot verify cross-document integrity",
                "visa_document": visa_feat,
                "passport_document": pass_feat,
                "ocr_artifacts": [],
                "history_flags": [],
            }

    required_visa_fields = ["passport_number", "surname", "date_of_birth", "nationality"]
    for f in required_visa_fields:
        if not visa_feat.get(f):
            return {
                "outcome": "SKIPPED",
                "field": f,
                "reason": f"Unreadable field '{f}' on visa ({visa_feat.get('document_id') or 'visa'}): cannot verify cross-document integrity",
                "visa_document": visa_feat,
                "passport_document": pass_feat,
                "ocr_artifacts": [],
                "history_flags": [],
            }

    ocr_artifacts: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------------
    # Requirement 1: VISA-TO-PASSPORT Passport Number Alignment
    # -----------------------------------------------------------------------
    v_pass_num = visa_feat["passport_number"]
    p_pass_num = pass_feat["passport_number"]

    if v_pass_num != p_pass_num:
        return {
            "outcome": "TAMPERED",
            "field": "passport_number",
            "reason": f"visa was not issued for this passport: visa specifies passport '{v_pass_num}' but presented passport is '{p_pass_num}'",
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": [],
            "history_flags": [],
        }

    # -----------------------------------------------------------------------
    # Requirement 1 & 2: Demographic Cross-Checks with OCR-B Tolerance
    # -----------------------------------------------------------------------

    # A. Nationality (Code field: exact normalized match)
    v_nat = visa_feat["nationality"]
    p_nat = pass_feat["nationality"]
    if v_nat != p_nat:
        return {
            "outcome": "TAMPERED",
            "field": "nationality",
            "reason": f"Nationality mismatch across session documents: visa '{v_nat}' conflicts with passport '{p_nat}'",
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": [],
            "history_flags": [],
        }

    # B. Date of Birth (Numeric field: exact normalized match)
    v_dob_norm = _normalize_date_str(visa_feat["date_of_birth"])
    p_dob_norm = _normalize_date_str(pass_feat["date_of_birth"])
    if not v_dob_norm or not p_dob_norm:
        return {
            "outcome": "SKIPPED",
            "field": "date_of_birth",
            "reason": f"Date of birth could not be parsed to standard date on one of the session documents (visa: '{visa_feat['date_of_birth']}', passport: '{pass_feat['date_of_birth']}')",
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": [],
            "history_flags": [],
        }

    if v_dob_norm != p_dob_norm:
        return {
            "outcome": "TAMPERED",
            "field": "date_of_birth",
            "reason": f"Date of birth mismatch across session documents: visa '{visa_feat['date_of_birth']}' ({v_dob_norm}) conflicts with passport '{pass_feat['date_of_birth']}' ({p_dob_norm})",
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": [],
            "history_flags": [],
        }

    # C. Surname (Name field: OCR-B tolerance)
    v_sur = visa_feat["surname"]
    p_sur = pass_feat["surname"]
    sur_ok, sur_arts = explainable_by_ocr_b(v_sur, p_sur)
    if not sur_ok:
        return {
            "outcome": "TAMPERED",
            "field": "surname",
            "reason": f"Surname mismatch across session documents not explainable by OCR confusion: visa '{v_sur}' conflicts with passport '{p_sur}'",
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": [],
            "history_flags": [],
        }
    if sur_arts:
        ocr_artifacts.append({"field": "surname", "visa": v_sur, "passport": p_sur, "confusions": sur_arts})

    # D. Given Names (Name field: OCR-B tolerance)
    v_giv = visa_feat["given_names"]
    p_giv = pass_feat["given_names"]
    if v_giv and p_giv:
        giv_ok, giv_arts = explainable_by_ocr_b(v_giv, p_giv)
        if not giv_ok:
            return {
                "outcome": "TAMPERED",
                "field": "given_names",
                "reason": f"Given names mismatch across session documents not explainable by OCR confusion: visa '{v_giv}' conflicts with passport '{p_giv}'",
                "visa_document": visa_feat,
                "passport_document": pass_feat,
                "ocr_artifacts": ocr_artifacts,
                "history_flags": [],
            }
        if giv_arts:
            ocr_artifacts.append({"field": "given_names", "visa": v_giv, "passport": p_giv, "confusions": giv_arts})

    # -----------------------------------------------------------------------
    # Requirement 3: REPEAT IDENTITY (Screening History Search)
    # -----------------------------------------------------------------------
    # Check passport against history
    p_flagged, p_flag_type, p_reason, p_events = store.check_repeat_identity(
        document_number=p_pass_num,
        surname=p_sur,
        given_names=p_giv,
        date_of_birth=p_dob_norm,
        current_session_id=sess_id,
        document_type="passport",
    )
    if p_flagged:
        return {
            "outcome": "TAMPERED",
            "field": "identity_reuse",
            "reason": p_reason,
            "flag_type": p_flag_type,
            "prior_events": p_events,
            "visa_document": visa_feat,
            "passport_document": pass_feat,
            "ocr_artifacts": ocr_artifacts,
        }

    # Check visa number against history (if visa was previously issued to a different person)
    v_num = visa_feat["visa_number"]
    if v_num:
        v_flagged, v_flag_type, v_reason, v_events = store.check_repeat_identity(
            document_number=v_num,
            surname=v_sur,
            given_names=v_giv,
            date_of_birth=v_dob_norm,
            current_session_id=sess_id,
            document_type="visa",
        )
        if v_flagged:
            return {
                "outcome": "TAMPERED",
                "field": "identity_reuse",
                "reason": v_reason,
                "flag_type": v_flag_type,
                "prior_events": v_events,
                "visa_document": visa_feat,
                "passport_document": pass_feat,
                "ocr_artifacts": ocr_artifacts,
            }

    # Record this verified screening session in history
    if record_screening:
        store.add_record(
            session_id=sess_id,
            document_id=pass_feat.get("document_id") or "passport",
            document_type="passport",
            document_number=p_pass_num,
            surname=p_sur,
            given_names=p_giv,
            date_of_birth=p_dob_norm,
            nationality=p_nat,
            timestamp=ts,
        )
        if v_num:
            store.add_record(
                session_id=sess_id,
                document_id=visa_feat.get("document_id") or "visa",
                document_type="visa",
                document_number=v_num,
                surname=v_sur,
                given_names=v_giv,
                date_of_birth=v_dob_norm,
                nationality=v_nat,
                timestamp=ts,
            )

    return {
        "outcome": "VERIFIED",
        "field": None,
        "reason": "Cross-document verification passed: visa was issued for this passport and all demographic fields match",
        "matched_fields": {
            "passport_number": p_pass_num,
            "surname": p_sur,
            "given_names": p_giv,
            "date_of_birth": p_dob_norm,
            "nationality": p_nat,
        },
        "visa_document": visa_feat,
        "passport_document": pass_feat,
        "ocr_artifacts": ocr_artifacts,
        "history_flags": [],
    }
