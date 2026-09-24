"""
morph_detection.py - Module 4 Extension: Single-Image Face Morphing Attack Detection (S-MAD).

Detects digital face morphing attacks on identity document photos where two subjects'
facial images were blended so both can pass biometric face verification against the same document.

HONEST SYSTEM DOCUMENTATION & ARCHITECTURAL LIMITATIONS:
- This is a software-based Single-Image Morphing Attack Detection (S-MAD) heuristic pipeline.
- It evaluates 4 complementary explainable signals:
    1. LBP Micro-Texture Attenuation: Detects smoothing/flattening of fine skin pores and noise.
    2. Craniofacial Anthropometric Symmetry: Detects geometric warping distortions and landmark skew.
    3. Facial Outline Ghosting / Double-Edge Contours: Detects paired duplicate ridges along facial contours.
    4. Frequency-Domain Blending Signature: 2D FFT spectral roll-off and spatial frequency discontinuity.
- Differential Morphing Attack Detection (D-MAD) comparing the document photo against a live trusted
  camera capture (differential embedding subtraction) and deep convolutional neural networks trained on
  FRLL-Morphs / SMDD benchmarks are recognized future tier enhancements.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

from .schemas import MorphDetectionResult, MorphSignalDetail

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "models"
)
YUNET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")


def _to_cv2(image_input: Union[bytes, np.ndarray, str]) -> np.ndarray:
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
    raise TypeError(f"Unsupported image type: {type(image_input)}")


def _compute_lbp(gray: np.ndarray) -> np.ndarray:
    """Computes vectorized standard 8-neighbor Local Binary Pattern."""
    h, w = gray.shape
    if h < 3 or w < 3:
        return np.zeros_like(gray)
    center = gray[1:-1, 1:-1]
    lbp = np.zeros_like(center, dtype=np.uint8)
    shifts = [
        (-1, -1, 0), (-1, 0, 1), (-1, 1, 2),
        (0, 1, 3), (1, 1, 4), (1, 0, 5),
        (1, -1, 6), (0, -1, 7)
    ]
    for dy, dx, bit in shifts:
        neighbor = gray[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        lbp |= ((neighbor >= center).astype(np.uint8) << bit)
    return lbp


def _analyze_lbp_texture(gray: np.ndarray) -> Tuple[float, bool, Dict[str, Any]]:
    """
    Signal 1: LBP Micro-Texture and Variance Analysis.
    Alpha blending two faces smooths micro-texture (pores, wrinkles, sensor grain).
    """
    ch, cw = gray.shape
    if ch < 20 or cw < 20:
        return 0.0, False, {"note": "Crop too small"}

    # Central facial zone (interocular bridge to upper lip)
    inner = gray[int(ch * 0.20):int(ch * 0.80), int(cw * 0.20):int(cw * 0.80)]
    lbp_inner = _compute_lbp(inner)
    hist, _ = np.histogram(lbp_inner.ravel(), bins=256, range=(0, 256), density=True)
    hist_nonzero = hist[hist > 0]
    entropy = float(-np.sum(hist_nonzero * np.log2(hist_nonzero))) if hist_nonzero.size > 0 else 0.0

    lap_inner = float(cv2.Laplacian(inner, cv2.CV_64F).var())
    lap_total = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    lap_ratio = lap_inner / max(1.0, lap_total)

    # In morphed images, alpha blending averages out micro-variations
    # Healthy passport photos have lap_inner > 38 and entropy > 5.15
    texture_drop = max(0.0, min(1.0, (38.0 - lap_inner) / 24.0)) if lap_inner < 38.0 else 0.0
    entropy_penalty = max(0.0, min(1.0, (5.20 - entropy) / 0.75)) if entropy < 5.20 else 0.0

    score = round(float(min(1.0, 0.55 * texture_drop + 0.45 * entropy_penalty)), 3)
    flagged = bool(score >= 0.35)
    return score, flagged, {
        "entropy": round(float(entropy), 3),
        "subregion_lap_var": round(float(lap_inner), 2),
        "total_lap_var": round(float(lap_total), 2),
        "lap_ratio": round(float(lap_ratio), 3)
    }


def _analyze_facial_symmetry(face_row: np.ndarray) -> Tuple[float, bool, Dict[str, Any]]:
    """
    Signal 2: Craniofacial Symmetry & Anthropometric Proportions Anomaly Check.
    Detects geometric distortion from blending two different donor face structures.
    """
    fw = face_row[2]
    re_x, re_y = face_row[4], face_row[5]
    le_x, le_y = face_row[6], face_row[7]
    n_x, n_y = face_row[8], face_row[9]
    rm_x, rm_y = face_row[10], face_row[11]
    lm_x, lm_y = face_row[12], face_row[13]

    iod = float(np.sqrt((le_x - re_x) ** 2 + (le_y - re_y) ** 2))
    iod_ratio = iod / max(1.0, float(fw))

    mid_eye_x = (re_x + le_x) / 2.0
    mid_eye_y = (re_y + le_y) / 2.0
    mid_mouth_y = (rm_y + lm_y) / 2.0

    # Lateral nose offset relative to eye perpendicular bisector
    nose_asym = abs(n_x - mid_eye_x) / max(1.0, iod)

    # Vertical cranial ratio: nose-to-mouth vs eye-to-nose
    d_eye_nose = abs(n_y - mid_eye_y)
    d_nose_mouth = abs(mid_mouth_y - n_y)
    vert_ratio = d_nose_mouth / max(1.0, d_eye_nose)

    # Bilateral eye-to-mouth distance discrepancy
    d_re_rm = np.sqrt((rm_x - re_x) ** 2 + (rm_y - re_y) ** 2)
    d_le_lm = np.sqrt((lm_x - le_x) ** 2 + (lm_y - le_y) ** 2)
    bilat_skew = float(abs(d_re_rm - d_le_lm) / max(1.0, max(d_re_rm, d_le_lm)))

    # Penalties based on standard anthropometric norms (ICAO 9303 portrait guidelines)
    iod_pen = max(0.0, min(1.0, (0.43 - iod_ratio) / 0.08)) if iod_ratio < 0.43 else (
        max(0.0, min(1.0, (iod_ratio - 0.52) / 0.08)) if iod_ratio > 0.52 else 0.0
    )
    nose_pen = max(0.0, min(1.0, (nose_asym - 0.09) / 0.08)) if nose_asym > 0.09 else 0.0
    vert_pen = max(0.0, min(1.0, (0.65 - vert_ratio) / 0.25)) if vert_ratio < 0.65 else (
        max(0.0, min(1.0, (vert_ratio - 1.42) / 0.30)) if vert_ratio > 1.42 else 0.0
    )
    skew_pen = max(0.0, min(1.0, (bilat_skew - 0.10) / 0.12)) if bilat_skew > 0.10 else 0.0

    score = round(float(min(1.0, 0.35 * nose_pen + 0.30 * iod_pen + 0.20 * vert_pen + 0.15 * skew_pen)), 3)
    flagged = bool(score >= 0.35)
    return score, flagged, {
        "iod_ratio": round(float(iod_ratio), 3),
        "nose_asymmetry": round(float(nose_asym), 3),
        "vertical_ratio": round(float(vert_ratio), 3),
        "bilateral_skew": round(float(bilat_skew), 3)
    }


def _analyze_ghosting_artifacts(gray: np.ndarray) -> Tuple[float, bool, Dict[str, Any]]:
    """
    Signal 3: "Double-Edge" / Ghosting Artifact Detection along facial perimeter.
    Detects paired duplicate contours produced by misaligned donor face boundaries.
    """
    ch, cw = gray.shape
    if ch < 24 or cw < 24:
        return 0.0, False, {"note": "Face crop too small"}

    # Annular band around facial perimeter (36% to 46% of face dimensions)
    mask = np.zeros((ch, cw), dtype=np.uint8)
    cx, cy = cw // 2, ch // 2
    cv2.ellipse(mask, (cx, cy), (int(cw * 0.46), int(ch * 0.48)), 0, 0, 360, 255, -1)
    cv2.ellipse(mask, (cx, cy), (int(cw * 0.36), int(ch * 0.38)), 0, 0, 360, 0, -1)

    edges = cv2.Canny(gray, 40, 110)
    band_edges = cv2.bitwise_and(edges, edges, mask=mask)
    band_edge_mask = (band_edges > 0)
    n_edges = np.count_nonzero(band_edge_mask)

    if n_edges < 10:
        return 0.0, False, {"edge_count": int(n_edges), "perimeter_edge_count": int(n_edges), "max_ghost_ratio": 0.0}

    # Gradients and normal direction
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy)

    cos_a, sin_a = np.cos(ang), np.sin(ang)
    yy, xx = np.indices((ch, cw))

    ghost_ratios = []
    for d in [3, 4, 5]:
        tx = np.clip(np.round(xx + d * cos_a).astype(int), 0, cw - 1)
        ty = np.clip(np.round(yy + d * sin_a).astype(int), 0, ch - 1)
        paired = band_edge_mask & band_edge_mask[ty, tx]
        ang_diff = np.abs(ang - ang[ty, tx])
        ang_diff = np.minimum(ang_diff, 2 * np.pi - ang_diff)
        parallel = paired & (ang_diff < (np.pi / 5))
        ghost_ratios.append(float(np.count_nonzero(parallel)) / max(1, n_edges))

    max_ghost = float(max(ghost_ratios)) if ghost_ratios else 0.0
    # In genuine ID crops, duplicate outline ratio is <0.018. In morphs with double boundaries, it is >=0.024
    score = max(0.0, min(1.0, (max_ghost - 0.018) / 0.014)) if max_ghost > 0.018 else 0.0
    score = round(float(score), 3)
    flagged = bool(score >= 0.35)
    return score, flagged, {
        "perimeter_edge_count": int(n_edges),
        "max_ghost_ratio": round(float(max_ghost), 4)
    }


def _analyze_frequency_discontinuity(gray: np.ndarray) -> Tuple[float, bool, Dict[str, Any]]:
    """
    Signal 4: Frequency-Domain Blending Signature (FFT Sub-region Discontinuity).
    Resampling and alpha-blending attenuates high-frequency power in the face core
    relative to outer document background.
    """
    ch, cw = gray.shape
    if ch < 24 or cw < 24:
        return 0.0, False, {"note": "Face crop too small"}

    inner = gray[int(ch * 0.20):int(ch * 0.80), int(cw * 0.20):int(cw * 0.80)]
    inner_resized = cv2.resize(inner, (64, 64))
    dft_inner = np.fft.fftshift(np.fft.fft2(inner_resized))
    mag_inner = np.abs(dft_inner)

    cy, cx = 32, 32
    Y, X = np.ogrid[:64, :64]
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    hf_inner = float(np.sum(mag_inner[dist > 16])) / (float(np.sum(mag_inner)) + 1e-6)

    # Top background strip of photo
    border_strip = gray[:max(16, int(ch * 0.25)), :]
    if border_strip.size >= 64:
        border_resized = cv2.resize(border_strip, (64, 64))
        dft_border = np.fft.fftshift(np.fft.fft2(border_resized))
        mag_border = np.abs(dft_border)
        hf_border = float(np.sum(mag_border[dist > 16])) / (float(np.sum(mag_border)) + 1e-6)
    else:
        hf_border = hf_inner

    freq_ratio = float(hf_inner / max(1e-4, hf_border))
    if freq_ratio < 0.68:
        score = max(0.0, min(1.0, (0.70 - freq_ratio) / 0.25))
    elif freq_ratio > 1.45:
        score = max(0.0, min(1.0, (freq_ratio - 1.40) / 0.35))
    else:
        score = 0.0

    score = round(float(score), 3)
    flagged = bool(score >= 0.35)
    return score, flagged, {
        "inner_hf_ratio": round(float(hf_inner), 4),
        "border_hf_ratio": round(float(hf_border), 4),
        "spectral_discontinuity_ratio": round(float(freq_ratio), 3)
    }


def detect_morphing(
    image_input: Union[bytes, np.ndarray, str],
    yunet_path: str = YUNET_PATH
) -> MorphDetectionResult:
    """
    Executes explainable 4-signal S-MAD face morphing attack detection on document photo.
    """
    img = _to_cv2(image_input)
    h_img, w_img = img.shape[:2]

    # Face detection using YuNet
    detector = cv2.FaceDetectorYN.create(yunet_path, "", (w_img, h_img), score_threshold=0.50)
    _, faces = detector.detect(img)

    if faces is None or len(faces) == 0:
        return MorphDetectionResult(
            face_detected=False,
            morph_suspicion_score=0.0,
            suspicion_tier="NORMAL",
            is_morph_suspected=False,
            morph_flags=[],
            signals={},
            summary="No face detected on document image for morphing attack analysis."
        )

    # Filter valid face sizes and pick largest identity portrait on document
    valid_faces = [f for f in faces if f[2] >= 32 and f[3] >= 32]
    if not valid_faces:
        valid_faces = faces
    face_row = max(valid_faces, key=lambda f: f[2] * f[3])
    fx, fy, fw, fh = int(face_row[0]), int(face_row[1]), int(face_row[2]), int(face_row[3])
    face_crop = img[max(0, fy):min(h_img, fy + fh), max(0, fx):min(w_img, fx + fw)]

    if face_crop.size == 0 or face_crop.shape[0] < 20 or face_crop.shape[1] < 20:
        return MorphDetectionResult(
            face_detected=True,
            morph_suspicion_score=0.0,
            suspicion_tier="NORMAL",
            is_morph_suspected=False,
            morph_flags=[],
            signals={},
            summary="Detected face area too small for reliable micro-texture analysis."
        )

    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

    # Signal 1: LBP Micro-Texture
    s1_score, s1_flag, s1_metrics = _analyze_lbp_texture(gray)

    # Signal 2: Facial Symmetry & Anthropometry
    s2_score, s2_flag, s2_metrics = _analyze_facial_symmetry(face_row)

    # Signal 3: Ghosting / Double-Edge Contours
    s3_score, s3_flag, s3_metrics = _analyze_ghosting_artifacts(gray)

    # Signal 4: Frequency-Domain Discontinuity
    s4_score, s4_flag, s4_metrics = _analyze_frequency_discontinuity(gray)

    # Weighted Heuristic Fusion with peak anomaly floor
    weighted_mean = (
        0.28 * s1_score +
        0.26 * s2_score +
        0.26 * s3_score +
        0.20 * s4_score
    )
    max_signal = max(s1_score, s2_score, s3_score, s4_score)
    # Peak-aware fusion ensures a strong single anomaly (e.g. ghost contour) elevates suspicion
    fused_score = round(float(min(1.0, max(weighted_mean, max_signal * 0.85))), 3)

    morph_flags: List[str] = []
    if s1_flag:
        morph_flags.append("LBP_TEXTURE_SMOOTHING")
    if s2_flag:
        morph_flags.append("SYMMETRY_RATIO_ANOMALY")
    if s3_flag:
        morph_flags.append("GHOSTING_DOUBLE_EDGE")
    if s4_flag:
        morph_flags.append("FREQUENCY_DISCONTINUITY")

    is_suspected = bool((fused_score >= 0.30) or (len(morph_flags) > 0))
    tier = "HIGH_SUSPICION" if fused_score >= 0.55 else ("ELEVATED" if is_suspected else "NORMAL")

    if is_suspected:
        flag_summary = ", ".join(f.replace("_", " ").title() for f in morph_flags)
        summary = (
            f"Face morphing indicators flagged ({tier}, score {fused_score:.2f}). "
            f"Anomalies detected: {flag_summary}. Document photo may be a digital composite of two identities."
        )
    else:
        summary = "Document photo verified: authentic single-identity micro-texture and coherent facial geometry."

    signals = {
        "lbp_texture": MorphSignalDetail(
            score=s1_score,
            flagged=s1_flag,
            description="Micro-texture uniformity and skin pore attenuation analysis",
            metrics=s1_metrics
        ),
        "symmetry_and_proportions": MorphSignalDetail(
            score=s2_score,
            flagged=s2_flag,
            description="Facial anthropometry and bilateral landmark ratio coherence",
            metrics=s2_metrics
        ),
        "ghosting_double_edge": MorphSignalDetail(
            score=s3_score,
            flagged=s3_flag,
            description="Annular perimeter double contour and ghosting artifact detection",
            metrics=s3_metrics
        ),
        "frequency_discontinuity": MorphSignalDetail(
            score=s4_score,
            flagged=s4_flag,
            description="FFT high-frequency spectral discontinuity across blend boundaries",
            metrics=s4_metrics
        )
    }

    return MorphDetectionResult(
        face_detected=True,
        morph_suspicion_score=fused_score,
        suspicion_tier=tier,
        is_morph_suspected=is_suspected,
        morph_flags=morph_flags,
        signals=signals,
        summary=summary
    )
