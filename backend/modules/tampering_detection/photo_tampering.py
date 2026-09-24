"""
photo_tampering.py - Photo region splicing and replacement detection.
Analyzes noise variance (Laplacian) and ELA error divergence between
the passport/ID photo region and the document substrate background.
"""
from typing import Optional, Tuple
import cv2
import numpy as np
from .schemas import PhotoTamperingResult
from ..face_verification.engine import get_face_engine


def check_photo_tampering(
    img: np.ndarray,
    ela_diff_gray: Optional[np.ndarray] = None
) -> PhotoTamperingResult:
    """
    Evaluates whether the photo region was spliced or replaced.
    """
    engine = get_face_engine()
    face_row, box, count = engine._detect_best_face(img)

    if box is None:
        return PhotoTamperingResult(
            photo_detected=False,
            noise_variance_ratio=1.0,
            ela_divergence=0.0,
            photo_splicing_detected=False,
            confidence=0.5
        )

    x, y, w, h = box.x, box.y, box.width, box.height
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

    # 1. Extract photo ROI
    photo_roi = gray[y:y+h, x:x+w]
    if photo_roi.size == 0:
        return PhotoTamperingResult(
            photo_detected=True,
            noise_variance_ratio=1.0,
            ela_divergence=0.0,
            photo_splicing_detected=False,
            confidence=0.5
        )

    # 2. Extract representative background paper ROI (excluding face)
    img_h, img_w = gray.shape[:2]
    mask = np.ones((img_h, img_w), dtype=np.uint8) * 255
    # Mask out face plus margin
    margin = int(min(w, h) * 0.2)
    x1 = max(0, x - margin)
    y1 = max(0, y - margin)
    x2 = min(img_w, x + w + margin)
    y2 = min(img_h, y + h + margin)
    mask[y1:y2, x1:x2] = 0

    bg_pixels = gray[mask == 255]
    if bg_pixels.size == 0:
        bg_pixels = gray

    # 3. High-frequency noise variance via Laplacian
    photo_lap = cv2.Laplacian(photo_roi, cv2.CV_64F)
    photo_noise_var = float(np.var(photo_lap))

    # Background noise in patches
    bg_var_samples = []
    step_y = max(20, img_h // 5)
    step_x = max(20, img_w // 5)
    for py in range(0, img_h - step_y, step_y):
        for px in range(0, img_w - step_x, step_x):
            # Check if patch overlaps with face
            if not (px + step_x > x1 and px < x2 and py + step_y > y1 and py < y2):
                patch = gray[py:py+step_y, px:px+step_x]
                patch_lap = cv2.Laplacian(patch, cv2.CV_64F)
                bg_var_samples.append(np.var(patch_lap))

    bg_noise_var = float(np.median(bg_var_samples)) if bg_var_samples else float(np.var(cv2.Laplacian(gray, cv2.CV_64F)))
    bg_noise_var = max(1.0, bg_noise_var)
    photo_noise_var = max(1.0, photo_noise_var)

    noise_ratio = round(photo_noise_var / bg_noise_var, 3)

    # 4. ELA error divergence between photo ROI and background
    ela_divergence = 0.0
    if ela_diff_gray is not None:
        photo_ela_mean = float(np.mean(ela_diff_gray[y:y+h, x:x+w]))
        bg_ela_mean = float(np.mean(ela_diff_gray[mask == 255]))
        ela_divergence = round(abs(photo_ela_mean - bg_ela_mean), 2)

    # 5. Splicing heuristic:
    # A genuine printed/scanned document has cohesive noise across paper and photo (ratio typically 0.5 to 3.0).
    # Spliced/pasted digital portraits often exhibit ratio > 5.0 or < 0.15, combined with high ELA divergence (> 25.0).
    splicing_detected = (noise_ratio > 4.5 or noise_ratio < 0.18) and ela_divergence > 22.0

    return PhotoTamperingResult(
        photo_detected=True,
        noise_variance_ratio=noise_ratio,
        ela_divergence=ela_divergence,
        photo_splicing_detected=splicing_detected,
        confidence=0.88
    )
