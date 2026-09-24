"""
liveness.py - Software-based face liveness detection (Part B).

Analyzes a burst of video frames to detect:
  1. Real biological motion (blink, head turn, smile) using face landmarks.
  2. Screen/print spoof texture signals using Laplacian variance and FFT moiré analysis.

DISCLAIMER: This is Phase 1 software-based liveness detection using a standard camera.
It raises the bar against casual print/screen spoofing but is NOT equivalent to:
  - Dedicated anti-spoofing hardware (IR sensors, structured light, depth cameras)
  - True iris biometrics (requires infrared iris-scanning cameras not present in this prototype)
Those are listed as future hardware-dependent enhancements, not implemented here.
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Path to face detection model (same as engine.py)
MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "models"
)
YUNET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")

# Landmark indices for YuNet 5-point output
# YuNet face row: [x, y, w, h, re_x, re_y, le_x, le_y, nose_x, nose_y, rm_x, rm_y, lm_x, lm_y, score]
YUNET_RIGHT_EYE = (4, 5)   # indices into face row
YUNET_LEFT_EYE = (6, 7)
YUNET_NOSE = (8, 9)
YUNET_RIGHT_MOUTH = (10, 11)
YUNET_LEFT_MOUTH = (12, 13)


def _to_cv2(image_bytes: bytes) -> np.ndarray:
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _detect_face_yunet(img: np.ndarray, yunet_path: str, conf: float = 0.5):
    """Detects faces with YuNet, returns face row with 15 values (5 landmarks + bbox + score)."""
    h, w = img.shape[:2]
    detector = cv2.FaceDetectorYN.create(yunet_path, "", (w, h), score_threshold=conf)
    _, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[-1])  # highest confidence


def _eye_aspect_ratio_yunet(face_row: np.ndarray) -> float:
    """
    Simplified EAR using YuNet's 2 eye landmarks + nose as vertical reference.
    A real EAR requires 6 points per eye (dlib 68-point), but with 5-point YuNet we
    approximate by measuring inter-eye distance relative to nose-to-eye distance as a proxy.
    A blink will bring eye landmarks closer together vertically; this proxy captures that.

    Returns pseudo-EAR: higher = eyes more open.
    """
    re_x, re_y = face_row[YUNET_RIGHT_EYE[0]], face_row[YUNET_RIGHT_EYE[1]]
    le_x, le_y = face_row[YUNET_LEFT_EYE[0]], face_row[YUNET_LEFT_EYE[1]]
    nose_x, nose_y = face_row[YUNET_NOSE[0]], face_row[YUNET_NOSE[1]]

    # Inter-eye distance (horizontal baseline)
    inter_eye_dist = float(np.linalg.norm([le_x - re_x, le_y - re_y]))

    # Average eye-to-nose vertical distance
    re_to_nose = float(abs(nose_y - re_y))
    le_to_nose = float(abs(nose_y - le_y))
    avg_eye_nose_dist = (re_to_nose + le_to_nose) / 2.0

    if avg_eye_nose_dist < 1e-6:
        return 0.3  # fallback: assume open

    return inter_eye_dist / (avg_eye_nose_dist + 1e-6)


def _head_yaw_proxy(face_row: np.ndarray) -> float:
    """
    Approximates head yaw (left/right turn) using the horizontal asymmetry
    of nose tip relative to eye midpoint.
    0.0 = perfectly frontal, positive = turned right, negative = turned left.
    """
    re_x = face_row[YUNET_RIGHT_EYE[0]]
    le_x = face_row[YUNET_LEFT_EYE[0]]
    nose_x = face_row[YUNET_NOSE[0]]

    eye_midpoint_x = (re_x + le_x) / 2.0
    inter_eye_dist = abs(le_x - re_x) + 1e-6
    yaw = (nose_x - eye_midpoint_x) / inter_eye_dist
    return float(yaw)


def _laplacian_variance(img: np.ndarray) -> float:
    """
    Measures texture sharpness via Laplacian variance.
    High variance = sharp real face skin texture.
    Low variance = blurry screen or flat printed photo.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _moire_score(img: np.ndarray) -> float:
    """
    Detects moiré/screen patterns via FFT frequency analysis.
    Screens often show periodic high-frequency interference patterns.
    Returns a score 0.0 (no moiré) to 1.0 (likely screen/print).

    NOTE: This is a supplementary heuristic. Natural camera noise can
    produce some high-frequency content, so this alone is not conclusive.
    The threshold is tuned conservatively to minimize false positives.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_f = np.float32(gray)
    dft = cv2.dft(gray_f, flags=cv2.DFT_COMPLEX_OUTPUT)
    dft_shifted = np.fft.fftshift(dft[:, :, 0] + 1j * dft[:, :, 1])
    magnitude = np.abs(dft_shifted)

    h, w = gray.shape
    # Look for suspicious spikes in mid-to-high frequency band (screen dot pitch)
    r_inner = min(h, w) // 8
    r_outer = min(h, w) // 3

    # Create annular mask for mid-frequency band
    Y, X = np.ogrid[:h, :w]
    cy, cx = h // 2, w // 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    mid_band_mask = (dist >= r_inner) & (dist <= r_outer)

    total_sum = float(np.sum(magnitude))
    if total_sum < 1e-6:
        return 0.0

    mid_ratio = float(np.sum(magnitude[mid_band_mask])) / total_sum
    # Periodic screen grid/moiré creates high mid-to-high frequency concentration (>0.40)
    score = min(1.0, max(0.0, (mid_ratio - 0.20) / 0.30))
    return round(score, 3)


def analyze_liveness(
    frames_bytes: List[bytes],
    challenge: str,
    yunet_path: str,
) -> Dict[str, Any]:
    """
    Analyze a burst of frames for liveness signals.

    Args:
        frames_bytes: List of image bytes (1.5-2 seconds of frames, ~5-15 frames).
        challenge: One of "blink", "turn_left", "turn_right", "smile".
        yunet_path: Path to the YuNet ONNX model.

    Returns:
        Dict with liveness_passed, liveness_score, challenge_result, texture_analysis, details.
    """
    if not frames_bytes:
        return _liveness_fail("No frames provided.", challenge)

    # Parse all frames
    frames = []
    for fb in frames_bytes:
        try:
            img = _to_cv2(fb)
            frames.append(img)
        except Exception as e:
            logger.warning(f"Liveness: could not decode frame: {e}")

    if not frames:
        return _liveness_fail("Could not decode any frames.", challenge)

    # ----- 1. Texture/Spoof Analysis on first frame -----
    first_frame = frames[0]
    lap_var = _laplacian_variance(first_frame)
    moire = _moire_score(first_frame)

    # Crop to face region if possible for better texture reading
    try:
        face_row = _detect_face_yunet(first_frame, yunet_path)
        if face_row is not None:
            x, y, fw, fh = int(face_row[0]), int(face_row[1]), int(face_row[2]), int(face_row[3])
            face_crop = first_frame[max(0, y):y + fh, max(0, x):x + fw]
            if face_crop.size > 0:
                lap_var = _laplacian_variance(face_crop)
                moire = _moire_score(face_crop)
    except Exception:
        pass

    # Supplementary texture heuristic:
    # Very low Laplacian variance (<15.0) = flat/blurry paper; moire > 0.85 = screen grid
    texture_spoof_signal = (lap_var < 15.0) or (moire > 0.85)
    texture_score = max(0.0, min(1.0, (lap_var - 10.0) / 100.0)) * (1.0 - moire)

    # ----- 2. Per-frame landmark tracking -----
    face_landmarks_seq: List[Optional[np.ndarray]] = []
    for img in frames:
        try:
            face_row = _detect_face_yunet(img, yunet_path)
            face_landmarks_seq.append(face_row)
        except Exception:
            face_landmarks_seq.append(None)

    detected_rows = [r for r in face_landmarks_seq if r is not None]
    if len(detected_rows) < max(2, len(frames) // 3):
        return _liveness_fail(
            f"Face not detected in enough frames ({len(detected_rows)}/{len(frames)}).",
            challenge,
            texture_spoof_signal=texture_spoof_signal,
            texture_score=texture_score,
            lap_var=lap_var,
            moire=moire,
        )

    # ----- 3. Challenge-specific motion analysis -----
    challenge_passed = False
    challenge_details = {}
    challenge_score = 0.0

    if challenge == "blink":
        ears = [_eye_aspect_ratio_yunet(r) for r in detected_rows]
        ear_range = float(np.max(ears) - np.min(ears))

        # Eye region frame-to-frame pixel dynamics (eyelid transition vs static photo)
        eye_diffs = []
        for i in range(len(frames) - 1):
            if face_landmarks_seq[i] is not None and face_landmarks_seq[i+1] is not None:
                r1 = face_landmarks_seq[i]
                r2 = face_landmarks_seq[i+1]
                g1 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
                g2 = cv2.cvtColor(frames[i+1], cv2.COLOR_BGR2GRAY)
                rx = int((r1[YUNET_RIGHT_EYE[0]] + r2[YUNET_RIGHT_EYE[0]]) / 2)
                ry = int((r1[YUNET_RIGHT_EYE[1]] + r2[YUNET_RIGHT_EYE[1]]) / 2)
                rw = max(4, int(r1[2] * 0.08))
                rh = max(3, int(r1[3] * 0.05))
                patch1 = g1[max(0, ry-rh):ry+rh, max(0, rx-rw):rx+rw]
                patch2 = g2[max(0, ry-rh):ry+rh, max(0, rx-rw):rx+rw]
                if patch1.shape == patch2.shape and patch1.size > 0:
                    eye_diffs.append(float(np.mean(cv2.absdiff(patch1, patch2))))

        max_eye_diff = float(max(eye_diffs)) if eye_diffs else 0.0
        challenge_passed = (ear_range > 0.15) or (max_eye_diff >= 4.0)
        challenge_score = min(1.0, max(ear_range / 0.30, max_eye_diff / 10.0))
        challenge_details = {
            "ear_range": round(ear_range, 3),
            "max_eye_diff": round(max_eye_diff, 2),
            "threshold": 4.0,
        }

    elif challenge in ("turn_left", "turn_right"):
        yaws = [_head_yaw_proxy(r) for r in detected_rows]
        yaw_range = float(max(yaws) - min(yaws))
        yaw_start = float(np.mean(yaws[:max(1, len(yaws) // 4)]))
        yaw_end = float(np.mean(yaws[-(max(1, len(yaws) // 4)):]))
        yaw_delta = yaw_end - yaw_start

        expected_direction = -1 if challenge == "turn_left" else 1
        directional_match = (yaw_delta * expected_direction) > 0.04
        challenge_passed = (yaw_range > 0.06) and directional_match
        challenge_score = min(1.0, yaw_range / 0.15)
        challenge_details = {
            "yaw_range": round(yaw_range, 3),
            "yaw_delta": round(yaw_delta, 3),
            "expected": challenge,
            "directional_match": directional_match,
            "threshold": 0.06,
        }

    elif challenge == "smile":
        mouth_ratios = []
        for r in detected_rows:
            rm_x, lm_x = r[YUNET_RIGHT_MOUTH[0]], r[YUNET_LEFT_MOUTH[0]]
            re_x, le_x = r[YUNET_RIGHT_EYE[0]], r[YUNET_LEFT_EYE[0]]
            face_w = abs(le_x - re_x) + 1e-6
            mouth_w = abs(lm_x - rm_x)
            mouth_ratios.append(mouth_w / face_w)
        ratio_range = float(max(mouth_ratios) - min(mouth_ratios))
        max_ratio = float(max(mouth_ratios))
        challenge_passed = ratio_range > 0.06 or max_ratio > 1.15
        challenge_score = min(1.0, (ratio_range + max(0.0, max_ratio - 1.0)) / 0.25)
        challenge_details = {
            "mouth_ratio_range": round(ratio_range, 3),
            "mouth_ratio_max": round(max_ratio, 3),
            "threshold": 0.06,
        }
    else:
        # Unknown challenge — pass through with neutral score
        challenge_passed = True
        challenge_score = 0.5
        challenge_details = {"note": f"Unknown challenge '{challenge}'; skipped motion check."}

    # ----- 4. Combined liveness score -----
    # Weights: challenge motion (0.65) + texture (0.35)
    # Texture is secondary/supplementary heuristic as documented in module docstring.
    combined_score = round(0.65 * challenge_score + 0.35 * texture_score, 3)

    # Overall pass: BOTH challenge must pass AND NOT a strong spoof signal
    # (texture spoof signal alone can fail liveness even with good motion — e.g. video replay)
    liveness_passed = challenge_passed and not texture_spoof_signal
    if not liveness_passed and not challenge_passed:
        fail_reason = f"Challenge '{challenge}' motion not detected in the frame sequence."
    elif not liveness_passed and texture_spoof_signal:
        fail_reason = (
            f"Spoof texture detected (Laplacian={lap_var:.1f}, Moiré={moire:.2f}). "
            "Frame appears to be a printed photo or screen display."
        )
    else:
        fail_reason = None

    return {
        "liveness_passed": liveness_passed,
        "liveness_score": combined_score,
        "challenge": challenge,
        "challenge_passed": challenge_passed,
        "challenge_score": round(challenge_score, 3),
        "challenge_details": challenge_details,
        "texture_analysis": {
            "laplacian_variance": round(lap_var, 2),
            "moire_score": round(moire, 3),
            "texture_score": round(texture_score, 3),
            "spoof_signal_detected": texture_spoof_signal,
            # NOTE: texture spoof detection is a supplementary heuristic only.
            # It raises the bar against casual screen/print spoofing but cannot
            # guarantee detection of sophisticated spoofs. Not hardware-grade.
        },
        "frames_analyzed": len(frames),
        "faces_detected": len(detected_rows),
        "fail_reason": fail_reason,
        "status": "LIVENESS_PASS" if liveness_passed else "LIVENESS_FAIL",
    }


def _liveness_fail(
    reason: str,
    challenge: str,
    texture_spoof_signal: bool = False,
    texture_score: float = 0.0,
    lap_var: float = 0.0,
    moire: float = 0.0,
) -> Dict[str, Any]:
    return {
        "liveness_passed": False,
        "liveness_score": 0.0,
        "challenge": challenge,
        "challenge_passed": False,
        "challenge_score": 0.0,
        "challenge_details": {},
        "texture_analysis": {
            "laplacian_variance": round(lap_var, 2),
            "moire_score": round(moire, 3),
            "texture_score": round(texture_score, 3),
            "spoof_signal_detected": texture_spoof_signal,
        },
        "frames_analyzed": 0,
        "faces_detected": 0,
        "fail_reason": reason,
        "status": "LIVENESS_FAIL",
    }


# Cache for detector to achieve ~20ms inference per frame
_YUNET_PROBE_CACHE: Dict[Tuple[str, float], cv2.FaceDetectorYN] = {}


def probe_single_frame(
    image_bytes: bytes,
    target_prompt: str = "fit_in_frame",
    yunet_path: str = YUNET_PATH,
) -> Dict[str, Any]:
    """
    Rapid single-frame probe for live camera guidance.
    Detects face positioning (fit in frame), head pose (yaw), and expression (smile/blink),
    evaluating if the current target prompt has been satisfied.
    """
    import time
    t0 = time.time()
    try:
        img = _to_cv2(image_bytes)
    except Exception as e:
        return {
            "face_detected": False,
            "fit_status": "NO_FACE",
            "prompt_message": "Could not decode video frame.",
            "target_fulfilled": False,
            "target_prompt": target_prompt,
            "error": str(e)
        }

    h, w = img.shape[:2]
    cache_key = (yunet_path, 0.45)
    if cache_key in _YUNET_PROBE_CACHE:
        detector = _YUNET_PROBE_CACHE[cache_key]
        detector.setInputSize((w, h))
    else:
        detector = cv2.FaceDetectorYN.create(yunet_path, "", (w, h), score_threshold=0.45)
        _YUNET_PROBE_CACHE[cache_key] = detector

    _, faces = detector.detect(img)
    face_row = None
    if faces is not None and len(faces) > 0:
        face_row = max(faces, key=lambda f: f[-1])

    elapsed_ms = round((time.time() - t0) * 1000, 1)

    if face_row is None:
        return {
            "face_detected": False,
            "fit_status": "NO_FACE",
            "fit_passed": False,
            "prompt_message": "No face detected — position your face inside the frame",
            "target_fulfilled": False,
            "target_prompt": target_prompt,
            "latency_ms": elapsed_ms,
            "bbox": None,
            "telemetry": {
                "face_coverage": 0.0,
                "yaw": 0.0,
                "yaw_deg": 0.0,
                "head_pose": "UNKNOWN",
                "is_turned_right": False,
                "is_turned_left": False,
                "mouth_ratio": 0.0,
                "smile_score": 0.0,
                "is_smiling": False,
                "ear": 0.0,
                "is_blinking": False,
            }
        }

    fx, fy, fw, fh = float(face_row[0]), float(face_row[1]), float(face_row[2]), float(face_row[3])
    norm_x = round(fx / w, 3)
    norm_y = round(fy / h, 3)
    norm_w = round(fw / w, 3)
    norm_h = round(fh / h, 3)
    cx = round(norm_x + norm_w / 2.0, 3)
    cy = round(norm_y + norm_h / 2.0, 3)
    face_coverage = round((fw * fh) / (w * h), 3)

    # Framing evaluation
    fit_status = "OPTIMAL"
    fit_passed = True
    if norm_h < 0.22 or face_coverage < 0.05:
        fit_status = "TOO_FAR"
        fit_passed = False
    elif norm_h > 0.72 or face_coverage > 0.55:
        fit_status = "TOO_CLOSE"
        fit_passed = False
    elif cx < 0.35:
        fit_status = "MOVE_RIGHT"
        fit_passed = False
    elif cx > 0.65:
        fit_status = "MOVE_LEFT"
        fit_passed = False
    elif cy < 0.30:
        fit_status = "MOVE_DOWN"
        fit_passed = False
    elif cy > 0.70:
        fit_status = "MOVE_UP"
        fit_passed = False

    # Head yaw
    yaw = _head_yaw_proxy(face_row)
    yaw_deg = round(yaw * 110.0, 1)
    if yaw > 0.06:
        head_pose = "TURNED_RIGHT"
        is_turned_right = True
        is_turned_left = False
    elif yaw < -0.06:
        head_pose = "TURNED_LEFT"
        is_turned_left = True
        is_turned_right = False
    else:
        head_pose = "CENTER"
        is_turned_right = False
        is_turned_left = False

    # Smile
    rm_x, lm_x = face_row[YUNET_RIGHT_MOUTH[0]], face_row[YUNET_LEFT_MOUTH[0]]
    re_x, le_x = face_row[YUNET_RIGHT_EYE[0]], face_row[YUNET_LEFT_EYE[0]]
    inter_eye = abs(le_x - re_x) + 1e-6
    mouth_w = abs(lm_x - rm_x)
    mouth_ratio = round(float(mouth_w / inter_eye), 3)
    smile_score = round(float(min(1.0, max(0.0, (mouth_ratio - 0.95) / 0.22))), 2)
    is_smiling = bool(mouth_ratio >= 1.05 or smile_score >= 0.50)

    # EAR
    ear = round(float(_eye_aspect_ratio_yunet(face_row)), 3)
    is_blinking = bool(ear < 0.22)

    # Target prompt fulfillment & message
    target_fulfilled = False
    prompt_message = ""

    if target_prompt == "fit_in_frame":
        target_fulfilled = fit_passed
        if fit_status == "OPTIMAL":
            prompt_message = "Position optimal! Hold steady..."
        elif fit_status == "TOO_FAR":
            prompt_message = "Move closer to the camera"
        elif fit_status == "TOO_CLOSE":
            prompt_message = "Move back slightly"
        elif fit_status == "MOVE_RIGHT":
            prompt_message = "Move slightly to your right"
        elif fit_status == "MOVE_LEFT":
            prompt_message = "Move slightly to your left"
        elif fit_status == "MOVE_DOWN":
            prompt_message = "Lower your face slightly"
        elif fit_status == "MOVE_UP":
            prompt_message = "Raise your face slightly"

    elif target_prompt == "turn_right":
        target_fulfilled = is_turned_right
        prompt_message = "Head turn detected!" if is_turned_right else "Slowly turn your head slightly to the RIGHT"

    elif target_prompt == "turn_left":
        target_fulfilled = is_turned_left
        prompt_message = "Head turn detected!" if is_turned_left else "Slowly turn your head slightly to the LEFT"

    elif target_prompt == "smile":
        target_fulfilled = is_smiling
        prompt_message = "Smile detected! Hold it" if is_smiling else "Now please SMILE for the camera"

    elif target_prompt == "blink":
        target_fulfilled = is_blinking
        prompt_message = "Blink detected!" if is_blinking else "Please BLINK your eyes"

    return {
        "face_detected": True,
        "fit_status": fit_status,
        "fit_passed": fit_passed,
        "target_prompt": target_prompt,
        "target_fulfilled": bool(target_fulfilled),
        "prompt_message": prompt_message,
        "latency_ms": elapsed_ms,
        "bbox": {
            "norm_x": float(norm_x),
            "norm_y": float(norm_y),
            "norm_w": float(norm_w),
            "norm_h": float(norm_h),
            "cx": float(cx),
            "cy": float(cy),
        },
        "telemetry": {
            "face_coverage": float(face_coverage),
            "yaw": round(float(yaw), 3),
            "yaw_deg": float(yaw_deg),
            "head_pose": str(head_pose),
            "is_turned_right": bool(is_turned_right),
            "is_turned_left": bool(is_turned_left),
            "mouth_ratio": float(mouth_ratio),
            "smile_score": float(smile_score),
            "is_smiling": bool(is_smiling),
            "ear": float(ear),
            "is_blinking": bool(is_blinking),
        }
    }

