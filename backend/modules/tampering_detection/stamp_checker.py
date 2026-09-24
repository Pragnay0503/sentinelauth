"""
stamp_checker.py - Official stamp, seal, and emblem forgery inspection.
Uses OpenCV ORB feature matching and contour regularity analysis
against official reference templates (Ashoka Stambh, government seals).
"""
import os
from typing import Optional
import cv2
import numpy as np
from .schemas import StampCheckResult

STAMPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "stamps")
os.makedirs(STAMPS_DIR, exist_ok=True)


def _get_reference_stamp() -> Optional[np.ndarray]:
    """Loads default reference stamp if present, or creates a standard synthetic template."""
    ref_path = os.path.join(STAMPS_DIR, "reference_emblem.png")
    if os.path.exists(ref_path):
        return cv2.imread(ref_path, cv2.IMREAD_GRAYSCALE)
    return None


def check_stamp_seal(img: np.ndarray) -> StampCheckResult:
    """
    Detects official emblem/seal region and verifies edge sharpness and contour regularity
    against authentic reference templates.
    If no reference asset is provisioned, returns not evaluated (stamp_detected=False, scores=0.0)
    with zero weight rather than emitting hardcoded heuristic values.
    """
    ref_stamp = _get_reference_stamp()
    if ref_stamp is None:
        # Module disabled / not evaluated: official reference emblem template not provisioned
        return StampCheckResult(
            stamp_detected=False,
            match_score=0.0,
            edge_regularity=0.0,
            forgery_suspected=False
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h_img, w_img = gray.shape[:2]

    # Official stamps/emblems reside in the upper third of the document
    upper_roi = gray[0:int(h_img * 0.45), 0:int(w_img * 0.60)]
    if upper_roi.size == 0:
        return StampCheckResult(
            stamp_detected=False,
            match_score=0.0,
            edge_regularity=0.0,
            forgery_suspected=False
        )

    # 1. Edge regularity of emblem region
    edges = cv2.Canny(upper_roi, 80, 200)
    edge_density = float(np.count_nonzero(edges)) / float(upper_roi.size)
    edge_regularity = min(1.0, max(0.1, edge_density * 10.0))

    # 2. Template / Feature Match against reference
    match_score = 0.0
    try:
        res = cv2.matchTemplate(upper_roi, ref_stamp, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        match_score = float(max(0.0, max_val))
    except Exception:
        orb = cv2.ORB_create(nfeatures=200)
        kp1, des1 = orb.detectAndCompute(upper_roi, None)
        kp2, des2 = orb.detectAndCompute(ref_stamp, None)
        if des1 is not None and des2 is not None:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            match_score = min(1.0, len(matches) / 30.0)

    # 3. Forgery determination
    forgery_suspected = (match_score < 0.35) or (edge_regularity < 0.20)

    return StampCheckResult(
        stamp_detected=True,
        match_score=round(float(match_score), 3),
        edge_regularity=round(float(edge_regularity), 3),
        forgery_suspected=forgery_suspected
    )
