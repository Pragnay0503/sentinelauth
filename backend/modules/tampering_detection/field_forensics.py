"""
field_forensics.py — Localized forensic analysis for individual document fields.

Performs localized Error Level Analysis (ELA) against neighboring field baselines
and measures font stroke width and baseline alignment consistency across peer fields.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


from ..ocr_extraction.layout_templates import get_layout_template, crop_region, RegionBBox
from .schemas import FieldForensicsResult


def _crop_ela(crop: np.ndarray, quality: int = 90, scale: float = 15.0) -> Tuple[float, float, str]:
    """
    Compute ELA on a specific crop.
    Returns (mean_diff, max_diff, heatmap_b64).
    """
    h, w = crop.shape[:2]
    if h < 4 or w < 4:
        return 0.0, 0.0, ""

    pil_img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil_img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    recomp_pil = Image.open(buf)

    orig_arr = np.array(pil_img, dtype=np.float32)
    recomp_arr = np.array(recomp_pil, dtype=np.float32)
    diff = np.abs(orig_arr - recomp_arr)

    diff_scaled = np.clip(diff * scale, 0, 255).astype(np.uint8)
    diff_gray = cv2.cvtColor(diff_scaled, cv2.COLOR_RGB2GRAY)

    mean_err = float(np.mean(diff_gray))
    max_err = float(np.max(diff_gray))

    heatmap_bgr = cv2.applyColorMap(diff_gray, cv2.COLORMAP_JET)
    _, enc = cv2.imencode(".jpg", heatmap_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    heatmap_b64 = "data:image/jpeg;base64," + base64.b64encode(enc.tobytes()).decode("ascii")

    return mean_err, max_err, heatmap_b64


def _measure_stroke_and_angle(crop: np.ndarray) -> Tuple[float, float]:
    """
    Measures estimated stroke width and baseline tilt angle of text inside a crop.
    """
    h, w = crop.shape[:2]
    if h < 8 or w < 8:
        return 1.0, 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    # Otsu thresholding
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Invert if majority of pixels are white
    if np.mean(thresh) > 127:
        thresh = cv2.bitwise_not(thresh)

    # Distance transform for stroke width
    dist = cv2.distanceTransform(thresh, cv2.DIST_L2, 5)
    non_zero = dist[dist > 0]
    stroke_width = float(np.mean(non_zero)) * 2.0 if len(non_zero) > 0 else 1.0

    # Baseline angle via minAreaRect of largest text contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles = []
    for c in contours:
        _bx, _by, _bw, _bh = cv2.boundingRect(c)
        cw, ch = int(_bw), int(_bh)
        if cw > 10 and ch > 6:
            rect = cv2.minAreaRect(c)
            (_, _), (rw, rh), ang = rect
            if rw < rh:
                ang += 90.0
            while ang > 45.0:
                ang -= 90.0
            while ang < -45.0:
                ang += 90.0
            angles.append(abs(float(ang)))

    avg_angle = float(np.mean(angles)) if angles else 0.0
    return round(float(stroke_width), 2), round(float(avg_angle), 2)


def analyze_field_region(
    image: np.ndarray,
    field_name: str,
    field_bbox: RegionBBox,
    peer_bboxes: Optional[Dict[str, RegionBBox]] = None,
    peer_crops: Optional[List[np.ndarray]] = None,
    document_type: str = "passport"
) -> FieldForensicsResult:
    """
    Performs localized forensic analysis on a specific field crop:
      1. Crops the field using normalized coordinates (ymin, xmin, ymax, xmax).
      2. Computes localized ELA error and compares against a baseline from neighbor fields.
      3. Measures stroke width & baseline consistency against peer fields.
      4. Decides likely_tampered with explainable scores calibrated against clean documents.
    """
    # 1. Crop target field
    target_crop, _ = crop_region(image, field_bbox, padding=0.01)
    target_mean_err, target_max_err, heatmap_b64 = _crop_ela(target_crop)
    target_sw, target_angle = _measure_stroke_and_angle(target_crop)

    # 2. Gather peer crops for localized baseline comparison
    resolved_peer_crops: List[np.ndarray] = []
    if peer_crops:
        resolved_peer_crops.extend(peer_crops)
    elif peer_bboxes:
        for p_name, p_bbox in peer_bboxes.items():
            if p_name != field_name:
                p_crop, _ = crop_region(image, p_bbox, padding=0.01)
                if p_crop.shape[0] >= 8 and p_crop.shape[1] >= 8:
                    resolved_peer_crops.append(p_crop)
            if len(resolved_peer_crops) >= 3:
                break

    # If no peers available from template, take an adjacent patch on the same image
    if not resolved_peer_crops:
        ymin, xmin, ymax, xmax = field_bbox
        bh = ymax - ymin
        # Shift vertically or horizontally
        alt_ymin = max(0.02, ymin - bh) if ymin > 0.20 else min(0.90, ymax + 0.02)
        alt_ymax = min(0.98, alt_ymin + bh)
        synthetic_bbox = (alt_ymin, xmin, alt_ymax, xmax)
        synth_crop, _ = crop_region(image, synthetic_bbox, padding=0.01)
        if synth_crop.shape[0] >= 8 and synth_crop.shape[1] >= 8:
            resolved_peer_crops.append(synth_crop)

    # 3. Compute baseline metrics from peer crops
    peer_means: List[float] = []
    peer_sws: List[float] = []
    peer_angles: List[float] = []

    for p in resolved_peer_crops:
        p_mean, _, _ = _crop_ela(p)
        p_sw, p_ang = _measure_stroke_and_angle(p)
        peer_means.append(p_mean)
        peer_sws.append(p_sw)
        peer_angles.append(p_ang)

    baseline_mean_ela = float(np.mean(peer_means)) if peer_means else 10.0
    baseline_sw = float(np.mean(peer_sws)) if peer_sws else target_sw
    baseline_angle = float(np.mean(peer_angles)) if peer_angles else target_angle

    # 4. Localized ELA anomaly score
    # Ratio against neighbor baseline eliminates uniform compression false positives!
    effective_baseline = max(baseline_mean_ela, 4.0)
    ela_ratio = target_mean_err / effective_baseline

    if ela_ratio <= 1.15:
        # Uniform with surrounding fields
        raw_ela_score = max(0.05, min(0.25, (ela_ratio - 0.8) * 0.3))
    elif ela_ratio <= 1.40:
        # Mild divergence
        raw_ela_score = 0.25 + (ela_ratio - 1.15) * 1.2
    else:
        # Significant localized compression diff (spliced/overlaid text)
        raw_ela_score = min(1.0, 0.55 + (ela_ratio - 1.40) * 0.35)

    # Boost score if target has high peak error spike
    if target_max_err > 210 and ela_ratio > 1.25:
        raw_ela_score = min(1.0, raw_ela_score + 0.15)

    ela_anomaly_score = round(max(0.0, min(1.0, raw_ela_score)), 2)

    # 5. Font consistency score (1.0 = consistent, < 0.5 = anomalous)
    sw_diff_ratio = abs(target_sw - baseline_sw) / max(baseline_sw, 0.8)
    angle_diff = abs(target_angle - baseline_angle)

    penalty_sw = min(0.50, sw_diff_ratio * 0.70)
    penalty_ang = min(0.40, (angle_diff / 10.0) * 0.40)
    font_consistency_score = round(max(0.05, min(1.0, 1.0 - (penalty_sw + penalty_ang))), 2)

    # 6. Overall likely_tampered determination using calibrated per-type, per-field thresholds
    doc_key = document_type.lower().strip()
    field_calib = CALIBRATED_THRESHOLDS.get(doc_key, {}).get(field_name, {})
    t_ela = field_calib.get("ela_p99", 0.65)
    t_font = field_calib.get("font_p01", 0.50)

    likely_tampered = (
        (ela_anomaly_score >= t_ela and font_consistency_score <= t_font)
        or (ela_anomaly_score >= min(1.0, max(0.70, t_ela + 0.07)))
        or (font_consistency_score <= max(0.20, t_font - 0.20) and ela_anomaly_score >= (t_ela * 0.70))
    )

    return FieldForensicsResult(
        ela_anomaly_score=float(ela_anomaly_score),
        font_consistency_score=float(font_consistency_score),
        likely_tampered=bool(likely_tampered),
        crop_ela_heatmap_b64=heatmap_b64,
        details={
            "target_mean_ela": round(float(target_mean_err), 2),
            "baseline_mean_ela": round(float(baseline_mean_ela), 2),
            "ela_divergence_ratio": round(float(ela_ratio), 2),
            "target_stroke_width": float(target_sw),
            "baseline_stroke_width": float(baseline_sw),
            "target_baseline_angle": float(target_angle),
            "baseline_angle": float(baseline_angle),
            "ela_threshold_p99": float(t_ela),
            "font_threshold_p01": float(t_font),
        }
    )


# Calibrated forensic thresholds (computed from 250 clean calibration documents under realistic capture variation at 99th percentile ELA and 1st percentile Font)
_THRESHOLDS_PATH = os.path.join(os.path.dirname(__file__), "calibrated_thresholds.json")

def _load_calibrated_thresholds() -> Dict[str, Dict[str, Dict[str, float]]]:
    if os.path.exists(_THRESHOLDS_PATH):
        try:
            with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            formatted = {}
            for dt, fields in raw.items():
                formatted[dt] = {}
                for fn, m in fields.items():
                    formatted[dt][fn] = {
                        "ela_p99": m.get("ela_threshold_p99", 0.70),
                        "font_p01": m.get("font_threshold_p01", 0.50),
                    }
            # Aliases
            if "national_id_pan" in formatted and "pan" not in formatted:
                formatted["pan"] = formatted["national_id_pan"]
            if "national_id_aadhaar" in formatted and "aadhaar" not in formatted:
                formatted["aadhaar"] = formatted["national_id_aadhaar"]
            if "national_id_voter" in formatted and "voter" not in formatted:
                formatted["voter"] = formatted["national_id_voter"]
            return formatted
        except Exception as e:
            logger.warning(f"Could not load calibrated_thresholds.json: {e}")

    return {
        "national_id_pan": {
            "pan_number": {"ela_p99": 0.740, "font_p01": 0.509},
            "name": {"ela_p99": 0.050, "font_p01": 0.775},
            "father_name": {"ela_p99": 0.700, "font_p01": 0.674},
            "dob": {"ela_p99": 0.741, "font_p01": 0.535},
        },
        "pan": {
            "pan_number": {"ela_p99": 0.740, "font_p01": 0.509},
            "name": {"ela_p99": 0.050, "font_p01": 0.775},
            "father_name": {"ela_p99": 0.700, "font_p01": 0.674},
            "dob": {"ela_p99": 0.741, "font_p01": 0.535},
        },
        "national_id_aadhaar": {
            "name": {"ela_p99": 0.711, "font_p01": 0.500},
            "dob": {"ela_p99": 0.055, "font_p01": 0.719},
            "gender": {"ela_p99": 0.050, "font_p01": 0.734},
            "aadhaar_number": {"ela_p99": 0.970, "font_p01": 0.530},
            "address": {"ela_p99": 0.190, "font_p01": 0.520},
        },
        "aadhaar": {
            "name": {"ela_p99": 0.711, "font_p01": 0.500},
            "dob": {"ela_p99": 0.055, "font_p01": 0.719},
            "gender": {"ela_p99": 0.050, "font_p01": 0.734},
            "aadhaar_number": {"ela_p99": 0.970, "font_p01": 0.530},
            "address": {"ela_p99": 0.190, "font_p01": 0.520},
        },
        "national_id_voter": {
            "epic_number": {"ela_p99": 0.930, "font_p01": 0.600},
            "name": {"ela_p99": 0.060, "font_p01": 0.810},
            "father_name": {"ela_p99": 0.060, "font_p01": 0.710},
            "gender": {"ela_p99": 0.250, "font_p01": 0.770},
            "dob": {"ela_p99": 0.260, "font_p01": 0.700},
        },
        "voter": {
            "epic_number": {"ela_p99": 0.930, "font_p01": 0.600},
            "name": {"ela_p99": 0.060, "font_p01": 0.810},
            "father_name": {"ela_p99": 0.060, "font_p01": 0.710},
            "gender": {"ela_p99": 0.250, "font_p01": 0.770},
            "dob": {"ela_p99": 0.260, "font_p01": 0.700},
        },
        "passport": {
            "surname": {"ela_p99": 0.070, "font_p01": 0.160},
            "given_names": {"ela_p99": 0.080, "font_p01": 0.680},
            "nationality": {"ela_p99": 0.770, "font_p01": 0.560},
            "dob": {"ela_p99": 0.670, "font_p01": 0.319},
            "sex": {"ela_p99": 0.085, "font_p01": 0.515},
            "expiry": {"ela_p99": 0.050, "font_p01": 0.243},
            "passport_number": {"ela_p99": 0.876, "font_p01": 0.124},
        },
        "visa": {
            "visa_number": {"ela_p99": 1.000, "font_p01": 0.165},
            "name": {"ela_p99": 0.075, "font_p01": 0.294},
            "passport_number": {"ela_p99": 0.050, "font_p01": 0.350},
            "valid_from": {"ela_p99": 0.336, "font_p01": 0.325},
            "expiry": {"ela_p99": 0.636, "font_p01": 0.340},
        },
    }

CALIBRATED_THRESHOLDS = _load_calibrated_thresholds()

# Explicit forensic field lists per document type
DOC_TYPE_FORENSIC_FIELDS: Dict[str, List[str]] = {
    "national_id_pan": ["pan_number", "name", "father_name", "dob"],
    "pan": ["pan_number", "name", "father_name", "dob"],
    "national_id_aadhaar": ["name", "dob", "gender", "aadhaar_number", "address"],
    "aadhaar": ["name", "dob", "gender", "aadhaar_number", "address"],
    "national_id_voter": ["epic_number", "name", "father_name", "gender", "dob"],
    "voter": ["epic_number", "name", "father_name", "gender", "dob"],
    "passport": ["surname", "given_names", "nationality", "dob", "sex", "expiry", "passport_number"],
    "driving_license": ["dl_number", "name", "dob", "expiry"],
    "visa": ["visa_number", "name", "passport_number", "valid_from", "expiry"],
}


def analyze_all_document_fields(
    image: np.ndarray,
    document_type: str = "passport",
    flagged_fields: Optional[List[str]] = None
) -> Dict[str, FieldForensicsResult]:
    """
    Runs localized forensics for key identity fields determined per document type
    from its layout template, plus any additional fields flagged by Module 2 cross-validation.
    Ensures no document type field is silently skipped.
    """
    doc_key = document_type.lower().strip()
    template = get_layout_template(doc_key)
    if not template and doc_key in ("auto", "unknown", "passport"):
        template = get_layout_template("passport")
    if not template:
        logger.warning(f"No layout template found for document_type='{document_type}'. Skipping field forensics.")
        return {}

    # 1. Determine target fields per document type
    if doc_key in DOC_TYPE_FORENSIC_FIELDS:
        target_fields = list(DOC_TYPE_FORENSIC_FIELDS[doc_key])
    else:
        # Fallback to all content fields in template (excluding layout containers)
        target_fields = [k for k in template.keys() if k not in ("header", "body", "info_block")]

    # 2. Append any extra fields flagged by upstream modules
    if flagged_fields:
        for ff in flagged_fields:
            if ff in template and ff not in target_fields:
                target_fields.append(ff)

    # 3. Build peer pool (use only target fields, avoiding huge headers or full-card containers)
    peer_pool = {k: template[k] for k in target_fields if k in template}

    results: Dict[str, FieldForensicsResult] = {}
    for tpl_key in target_fields:
        if tpl_key not in template:
            logger.warning(
                f"Field '{tpl_key}' expected for doc_type='{document_type}' but missing from template keys: {list(template.keys())}"
            )
            continue

        bbox = template[tpl_key]
        peer_bboxes = {k: v for k, v in peer_pool.items() if k != tpl_key}
        res = analyze_field_region(
            image=image,
            field_name=tpl_key,
            field_bbox=bbox,
            peer_bboxes=peer_bboxes if peer_bboxes else None,
            document_type=doc_key
        )
        results[tpl_key] = res

    logger.info(f"[{document_type}] Field forensics analyzed {len(results)} fields: {list(results.keys())}")
    return results



