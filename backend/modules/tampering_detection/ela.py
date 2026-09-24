"""
ela.py - Error Level Analysis (ELA) implementation.
Performs real re-compression diffing against JPEG baseline,
highlighting areas edited or saved at different compression levels.
"""
import base64
import io
from typing import Tuple, Union
import cv2
import numpy as np
from PIL import Image
from .schemas import ELAResult


def compute_ela(
    image_input: Union[bytes, np.ndarray, str],
    quality: int = 90,
    scale: float = 15.0,
    anomaly_threshold: float = 0.35
) -> Tuple[ELAResult, np.ndarray]:
    """
    Computes real Error Level Analysis.
    Returns:
        (ELAResult, raw_diff_gray_numpy)
    """
    # 1. Load original as RGB PIL Image
    if isinstance(image_input, np.ndarray):
        orig_pil = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
    elif isinstance(image_input, str):
        orig_pil = Image.open(image_input).convert("RGB")
    elif isinstance(image_input, (bytes, bytearray)):
        orig_pil = Image.open(io.BytesIO(image_input)).convert("RGB")
    else:
        raise TypeError(f"Unsupported image input type: {type(image_input)}")

    # 2. Save to in-memory JPEG at designated quality
    buf = io.BytesIO()
    orig_pil.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    recompressed_pil = Image.open(buf)

    # 3. Compute pixel-wise absolute difference
    orig_arr = np.array(orig_pil, dtype=np.float32)
    recomp_arr = np.array(recompressed_pil, dtype=np.float32)
    diff = np.abs(orig_arr - recomp_arr)

    # 4. Scale difference for visualization
    diff_scaled = np.clip(diff * scale, 0, 255).astype(np.uint8)
    diff_gray = cv2.cvtColor(diff_scaled, cv2.COLOR_RGB2GRAY)

    # 5. Generate Colormap Heatmap (Jet)
    heatmap_bgr = cv2.applyColorMap(diff_gray, cv2.COLORMAP_JET)

    # 6. Statistical metrics
    mean_err = float(np.mean(diff_gray))
    max_err = float(np.max(diff_gray))
    p95_err = float(np.percentile(diff_gray, 95))

    # Anomaly score: normal camera documents have mean_err around 10-25 and p95 around 40-70.
    # Heavily spliced or multi-compressed images produce localized bright artifacts (p95 > 120 or max > 220).
    raw_anomaly = (p95_err / 180.0) * 0.6 + (mean_err / 50.0) * 0.4
    anomaly_score = round(min(1.0, max(0.0, raw_anomaly)), 4)
    flagged = anomaly_score >= anomaly_threshold

    # 7. Encode Heatmap to Base64
    _, enc_heatmap = cv2.imencode(".jpg", heatmap_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    heatmap_b64 = "data:image/jpeg;base64," + base64.b64encode(enc_heatmap.tobytes()).decode("ascii")

    result = ELAResult(
        anomaly_score=anomaly_score,
        mean_error=round(mean_err, 2),
        max_error=round(max_err, 2),
        heatmap_b64=heatmap_b64,
        flagged=flagged
    )
    return result, diff_gray
