"""
test_tampering.py - Unit and forensic tests for Error Level Analysis, EXIF, and tampering detection.
"""
import numpy as np
import cv2
from PIL import Image
import io
from backend.modules.tampering_detection.ela import compute_ela
from backend.modules.tampering_detection.exif_inspector import inspect_exif
from backend.modules.tampering_detection.detector import detect_tampering


def test_compute_ela_generates_valid_heatmap():
    # Create test RGB image
    test_img = np.zeros((200, 300, 3), dtype=np.uint8)
    cv2.putText(test_img, "OFFICIAL IDENTITY", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    ela_res, diff = compute_ela(test_img, quality=90)
    assert ela_res.anomaly_score >= 0.0
    assert ela_res.anomaly_score <= 1.0
    assert ela_res.mean_error >= 0.0
    assert ela_res.heatmap_b64.startswith("data:image/jpeg;base64,")
    assert diff.shape == (200, 300)


def test_exif_software_detection():
    # Create an in-memory image with a simulated Photoshop software tag in PNG text chunks
    from PIL import PngImagePlugin
    pil_img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Software", "Adobe Photoshop 2024")
    
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", pnginfo=png_info)
    buf.seek(0)
    
    exif_res = inspect_exif(buf.getvalue())
    assert exif_res.is_suspicious is True
    assert "Photoshop" in exif_res.editing_tools_found


def test_full_tampering_detector():
    test_img = np.ones((250, 400, 3), dtype=np.uint8) * 200
    cv2.putText(test_img, "GOVT OF INDIA", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.putText(test_img, "AADHAAR NUMBER", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    
    res = detect_tampering(test_img)
    assert 0.0 <= res.tampering_score <= 1.0
    assert isinstance(res.is_tampered, bool)
    assert len(res.explanation) > 0
