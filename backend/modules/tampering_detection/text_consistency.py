"""
text_consistency.py - Text line font metric and baseline alignment consistency.
Uses Canny edge detection, morphological contour grouping, and bounding box variance
to detect digitally modified characters, misaligned text insertions, or font replacements.
"""
from typing import List, Tuple
import cv2
import numpy as np
from .schemas import TextConsistencyResult


def check_text_consistency(img: np.ndarray) -> TextConsistencyResult:
    """
    Analyzes font height uniformity, baseline slope variance, and edge sharpness.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h_img, w_img = gray.shape[:2]

    # 1. Edge detection for character strokes
    edges = cv2.Canny(gray, 50, 150)

    # 2. Horizontal morphological dilation to group words into text line segments
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    dilated = cv2.dilate(edges, kernel, iterations=1)

    # 3. Find connected contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    text_boxes = []
    line_heights = []
    baseline_angles = []

    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        x, y, w, h = int(bx), int(by), int(bw), int(bh)
        # Filter for plausible text lines (width > 20px, height between 8px and 60px, aspect ratio > 1.5)
        if w > 25 and 8 <= h <= 65 and (w / h) > 1.2:
            # Exclude large document borders or photo bounding boxes
            if w < w_img * 0.90 and h < h_img * 0.40:
                text_boxes.append((x, y, w, h))
                line_heights.append(h)

                # MinAreaRect to compute subtle baseline tilt angle (-45 to 45 deg)
                rect = cv2.minAreaRect(cnt)
                (cx, cy), (rw, rh), angle = rect
                # Ensure width is the major axis for horizontal text
                if rw < rh:
                    rw, rh = rh, rw
                    angle += 90.0
                # Normalize angle to [-45, 45] relative to horizontal
                while angle > 45.0:
                    angle -= 90.0
                while angle < -45.0:
                    angle += 90.0
                baseline_angles.append(abs(angle))

    line_count = len(text_boxes)
    if line_count < 3:
        return TextConsistencyResult(
            text_line_count=line_count,
            font_size_variance=0.0,
            baseline_alignment_variance=0.0,
            text_manipulation_suspected=False,
            confidence=0.60
        )

    # Calculate variances
    height_std = float(np.std(line_heights))
    angle_std = float(np.std(baseline_angles))

    # In genuine government issued ID cards, fonts follow 2-3 standard sizes (titles, body, numbers)
    # and baselines are strictly parallel (angle std < 2.5 deg).
    # Heavily altered documents with spliced text boxes exhibit angle_std > 6.0 deg or erratic height variations.
    manipulation_suspected = angle_std > 5.5 or (height_std > 16.0 and angle_std > 3.5)

    return TextConsistencyResult(
        text_line_count=line_count,
        font_size_variance=round(height_std, 2),
        baseline_alignment_variance=round(angle_std, 2),
        text_manipulation_suspected=manipulation_suspected,
        confidence=0.85
    )
