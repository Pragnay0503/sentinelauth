"""
detector.py - Master Tampering Detection Orchestrator (Module 3).
Executes all forensic checks and combines them into an explainable tampering score (0.0 - 1.0).

Scoring rules:
1. Field forensics and ELA are strictly INFORMATIONAL:
   - They cannot produce a TAMPERED outcome or push risk score into CRITICAL on their own.
   - Only structural checks (Verhoeff/format, QR decode-and-compare, MRZ check digits,
     print-vs-MRZ, cross-document, watchlist, expiry) decide document outcomes.
2. Re-encoded or screenshotted inputs (identified via JPEG quantization table analysis
   or missing camera capture metadata):
   - Pixel-forensic signals are marked NOT_EVALUATED with reason:
     "image re-encoded; pixel forensics unreliable for this capture".
   - Tampering score is 0.0, allowing structural checks to decide the outcome normally.
"""
import io
from typing import Any, Dict, List, Optional, Tuple, Union
import cv2
import numpy as np
from PIL import Image

from .schemas import TamperingResult
from .ela import compute_ela
from .exif_inspector import inspect_exif
from .photo_tampering import check_photo_tampering
from .text_consistency import check_text_consistency
from .stamp_checker import check_stamp_seal
from .field_forensics import analyze_all_document_fields


def _load_image(image_input: Union[bytes, np.ndarray, str]) -> np.ndarray:
    if isinstance(image_input, np.ndarray):
        return image_input
    if isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None:
            raise ValueError(f"Could not load image from path: {image_input}")
        return img
    if isinstance(image_input, (bytes, bytearray)):
        pil_img = Image.open(io.BytesIO(image_input)).convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    raise TypeError(f"Unsupported image input type: {type(image_input)}")


def _inspect_reencoding(image_input: Union[bytes, np.ndarray, str]) -> Tuple[bool, str]:
    """
    Detects if the input image was re-encoded, screenshotted, or stripped of original camera capture metadata.
    Checks:
      1. Non-JPEG format (PNG, WEBP, BMP, etc. which are standard screenshot / web export formats).
      2. Missing expected hardware camera capture metadata (Make, Model, DateTimeOriginal, etc.).
      3. JPEG quantization table inspection (e.g. flat tables from standard software re-encoders).
    """
    try:
        pil_img = None
        if isinstance(image_input, (bytes, bytearray)):
            pil_img = Image.open(io.BytesIO(image_input))
        elif isinstance(image_input, str):
            pil_img = Image.open(image_input)
        elif isinstance(image_input, np.ndarray):
            return True, "image re-encoded; pixel forensics unreliable for this capture"

        if pil_img is None:
            return True, "image re-encoded; pixel forensics unreliable for this capture"

        fmt = (pil_img.format or "").upper()
        # 1. Format check: PNG, WEBP, etc. are typical for screenshots / re-encodings
        if fmt not in ("JPEG", "JPG", "TIFF"):
            return True, "image re-encoded; pixel forensics unreliable for this capture"

        # 2. Camera capture metadata check
        raw_exif = None
        try:
            raw_exif = pil_img.getexif()
        except Exception:
            raw_exif = None

        has_camera_metadata = False
        if raw_exif and len(raw_exif) > 0:
            camera_tags = {271, 272, 36867, 37386, 33434, 34855}
            if any(t in raw_exif for t in camera_tags):
                has_camera_metadata = True

        if not has_camera_metadata:
            return True, "image re-encoded; pixel forensics unreliable for this capture"

        # 3. JPEG quantization table inspection
        q_tables = getattr(pil_img, "quantization", None)
        if q_tables and isinstance(q_tables, dict):
            luma_table = q_tables.get(0, [])
            if luma_table and len(luma_table) >= 64:
                # If high-frequency coefficients are all <= 2, it's a recompressed/synthetic export
                if max(luma_table) <= 2:
                    return True, "image re-encoded; pixel forensics unreliable for this capture"

        return False, ""
    except Exception:
        return True, "image re-encoded; pixel forensics unreliable for this capture"


def detect_tampering(
    image_input: Union[bytes, np.ndarray, str],
    document_type: str = "passport",
    flagged_fields: Optional[List[str]] = None,
) -> TamperingResult:
    """
    Executes the full forensic tampering pipeline and returns a TamperingResult.

    Pipeline steps
    ──────────────
    0.  Re-encoding / screenshot detection (gates pixel-forensic modules).
    1.  Error Level Analysis (ELA) – INFORMATIONAL only; contribution = 0.0.
    2.  EXIF / metadata editing-software inspection.
    3.  Photo-region noise variance / splicing verification.
    4.  Text baseline alignment & font-metric consistency.
    5.  Stamp / emblem edge-feature verification.
    6.  Localized per-field forensics – INFORMATIONAL only; contribution = 0.0.

    Score composition
    ─────────────────
    • ELA contribution:             always 0.0  (INFORMATIONAL)
    • Field-forensics contribution: always 0.0  (INFORMATIONAL)
    • Photo-noise contribution:     0.30 if splicing detected (0.0 if re-encoded)
    • EXIF contribution:            0.15 if editing software  (0.0 if re-encoded)
    • Text-metric contribution:     0.15 if manipulation found(0.0 if re-encoded)
    • Stamp contribution:           0.10 if forgery suspected (0.0 if re-encoded)

    When is_reencoded is True, ALL pixel-forensic contributions are 0.0 and each
    affected module is tagged [NOT_EVALUATED] in the explanation.  Structural
    checks still run and decide outcome = TAMPERED | VERIFIED.
    """
    img = _load_image(image_input)

    # Inspect for re-encoding / screenshot / missing camera metadata
    is_reencoded, reencoded_reason = _inspect_reencoding(image_input)

    # 1. Error Level Analysis
    ela_res, diff_gray = compute_ela(image_input, quality=90, scale=15.0)

    # 2. Metadata / EXIF Inspection
    raw_bytes = None
    if isinstance(image_input, (bytes, bytearray)):
        raw_bytes = bytes(image_input)
    elif isinstance(image_input, str):
        with open(image_input, "rb") as f:
            raw_bytes = f.read()
    exif_res = inspect_exif(raw_bytes if raw_bytes else image_input)

    # 3. Photo Region Tampering
    photo_res = check_photo_tampering(img, diff_gray)

    # 4. Text Region Consistency
    text_res = check_text_consistency(img)

    # 5. Stamp & Seal Check
    stamp_res = check_stamp_seal(img)

    # 6. Localized Field Forensics
    field_forensics = analyze_all_document_fields(
        img,
        document_type=document_type,
        flagged_fields=flagged_fields
    )

    # Shared accumulators for both re-encoded and hardware-capture paths
    flagged_checks: List[str] = []
    explanation: List[str] = []

    # ── ELA: INFORMATIONAL – contribution always 0.0 ─────────────────────────
    ela_contrib = 0.0
    if ela_res.flagged:
        explanation.append(
            f"[INFORMATIONAL] Error Level Analysis: anomaly score {ela_res.anomaly_score:.2f}. "
            f"Not used in outcome scoring (thresholds unreliable for real documents)."
        )

    # ── Field forensics: INFORMATIONAL – contribution always 0.0 ──────────────
    # Collect flagged fields BEFORE resetting likely_tampered so diagnostic
    # values are still available for the explanation text.
    local_tampered_fields = [f for f, r in field_forensics.items() if r.likely_tampered]
    # Reset the flag so downstream consumers cannot misread it as a structural finding.
    for r in field_forensics.values():
        r.likely_tampered = False

    field_tamper_contrib = 0.0  # Always 0.0

    for tf in set(local_tampered_fields):
        r = field_forensics[tf]
        field_name_clean = tf.replace("_", " ").title()
        explanation.append(
            f"[INFORMATIONAL] Localized compression variance noted in '{field_name_clean}' "
            f"(ELA anomaly {r.ela_anomaly_score:.2f}, font consistency {r.font_consistency_score:.2f}). "
            f"Not used in outcome scoring (structural checks decide the outcome)."
        )

    # ── Pixel-forensic structural signals ─────────────────────────────────────
    # When re-encoded / screenshotted: all pixel-forensic contributions → 0.0,
    # tagged NOT_EVALUATED.  Structural checks still run and decide outcome.
    if is_reencoded:
        explanation.insert(
            0,
            "[NOT_EVALUATED] image re-encoded; pixel forensics unreliable for this capture. "
            "Structural checks continue normally and decide the outcome."
        )
        photo_contrib = 0.0
        exif_contrib = 0.0
        text_contrib = 0.0
        stamp_contrib = 0.0
        # Silence boolean flags so serialised consumers are not misled
        photo_res.photo_splicing_detected = False
        text_res.text_manipulation_suspected = False
        stamp_res.forgery_suspected = False

    else:
        # ── Hardware-capture path: pixel forensics are evaluated ───────────

        # Photo splicing (noise-based; not ELA-based)
        photo_contrib = 0.30 if photo_res.photo_splicing_detected else (
            0.10 if photo_res.noise_variance_ratio > 3.5 else 0.0
        )
        if photo_res.photo_splicing_detected:
            flagged_checks.append("PHOTO_REPLACEMENT_SUSPECTED")
            explanation.append(
                f"Face photo noise variance ratio ({photo_res.noise_variance_ratio:.2f}) "
                f"diverged significantly from document paper texture."
            )

        # EXIF editing-software signature
        exif_contrib = 0.15 if exif_res.is_suspicious else 0.0
        if exif_res.editing_tools_found:
            flagged_checks.append("EDITING_SOFTWARE_SIGNATURE")
            explanation.append(
                f"Image metadata revealed traces of digital editing software: "
                f"{', '.join(exif_res.editing_tools_found)}."
            )

        # Text metric consistency
        text_contrib = 0.15 if text_res.text_manipulation_suspected else 0.0
        if text_res.text_manipulation_suspected:
            flagged_checks.append("INCONSISTENT_TEXT_METRICS")
            explanation.append(
                f"Detected inconsistent text line baselines or stroke height variance "
                f"(angle variance {text_res.baseline_alignment_variance}°)."
            )

        # Stamp / seal edge irregularity
        stamp_contrib = 0.10 if (stamp_res.stamp_detected and stamp_res.forgery_suspected) else 0.0
        if stamp_res.stamp_detected and stamp_res.forgery_suspected:
            flagged_checks.append("IRREGULAR_EMBLEM_EDGES")
            explanation.append(
                f"Official seal or emblem edges show abnormal blur or low match "
                f"confidence ({stamp_res.match_score:.2f})."
            )

    raw_tamper_score = photo_contrib + exif_contrib + text_contrib + stamp_contrib
    final_tampering_score = round(min(1.0, max(0.0, raw_tamper_score)), 3)
    is_tampered = final_tampering_score >= 0.40

    if not explanation:
        explanation.append("All forensic integrity tests passed: consistent compression, natural noise gradients, and aligned typography.")

    contributions: Dict[str, float] = {
        "ela": 0.0,                               # Always informational
        "field_forensics": 0.0,                   # Always informational
        "photo": round(float(photo_contrib), 3),
        "exif": round(float(exif_contrib), 3),
        "text": round(float(text_contrib), 3),
        "stamp": round(float(stamp_contrib), 3),
    }

    outcome = "TAMPERED" if is_tampered else "VERIFIED"
    if is_reencoded:
        outcome_reason = (
            "Structural checks indicate tampering despite re-encoded input."
            if is_tampered
            else "Pixel forensics not evaluated (re-encoded input); outcome based on structural checks only."
        )
    else:
        outcome_reason = (
            "Forensic tampering indicators exceed threshold."
            if is_tampered
            else "Forensic integrity verified."
        )

    return TamperingResult(
        tampering_score=final_tampering_score,
        is_tampered=is_tampered,
        confidence=0.85 if is_reencoded else 0.89,
        ela=ela_res,
        exif=exif_res,
        photo_region=photo_res,
        text_consistency=text_res,
        stamp_seal=stamp_res,
        field_forensics=field_forensics,
        flagged_checks=flagged_checks,
        explanation=explanation,
        module_contributions=contributions,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )
