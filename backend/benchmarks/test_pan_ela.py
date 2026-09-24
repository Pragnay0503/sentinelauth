import os, sys, cv2, numpy as np
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from backend.modules.ocr_extraction.layout_templates import get_layout_template
from backend.modules.tampering_detection.field_forensics import _crop_ela, crop_region

img = cv2.imread(os.path.join(BASE_DIR, 'data/calibration_dataset/images/pan_calib_001.png'))
tpl = get_layout_template('national_id_pan')
for f, bbox in tpl.items():
    crop, _ = crop_region(img, bbox, padding=0.01)
    mean_err, max_err, _ = _crop_ela(crop)
    print(f"{f}: mean_err={mean_err:.2f}, max_err={max_err:.2f}, shape={crop.shape}")
