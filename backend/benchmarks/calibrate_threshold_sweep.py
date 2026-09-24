import json
import os
import sys
import cv2
import re
import numpy as np

BASE_DIR = r"c:\Users\thada\OneDrive\Desktop\SIHHH"
sys.path.insert(0, BASE_DIR)
from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
from backend.modules.ocr_extraction.label_anchor import boxes_from_raw_results

CALIB_MANIFEST = os.path.join(BASE_DIR, "data", "calibration_dataset", "manifest.json")

with open(CALIB_MANIFEST, "r", encoding="utf-8") as f:
    manifest = json.load(f)

reader = _easyocr_engine.get_reader("en")

# We test all 50 PAN cards in calibration dataset (which is the primary structured field with slot repairs)
pan_docs = [x for x in manifest if x.get("document_type") == "national_id_pan"]

correct_confs = []
repairable_misread_confs = []
unrepairable_confs = []

print(f"Calibrating threshold over {len(pan_docs)} clean PAN calibration documents...")

for doc in pan_docs:
    img = cv2.imread(os.path.join(BASE_DIR, doc["file_path"]))
    if img is None:
        continue
    raw = reader.readtext(img)
    boxes = boxes_from_raw_results(raw, img.shape[:2])
    gt_pan = doc["ground_truth_fields"]["pan_number"]

    # Locate the PAN box
    pan_box = None
    for b in boxes:
        txt = re.sub(r"[^A-Z0-9]", "", b.text.upper())
        if 8 <= len(txt) <= 12 and (txt[:3] == gt_pan[:3] or (0.15 <= b.ymin <= 0.35 and 0.03 <= b.xmin <= 0.40)):
            pan_box = b
            break

    if pan_box:
        raw_txt = re.sub(r"[^A-Z0-9]", "", pan_box.text.upper())
        conf = pan_box.confidence
        if raw_txt == gt_pan:
            correct_confs.append((doc["id"], conf, raw_txt))
        else:
            # Check if this misread is repairable by slot substitution
            p_prefix = raw_txt[:5]
            p_digits = raw_txt[5:9]
            p_suffix = raw_txt[9:10]
            p_digits_rep = (
                p_digits
                .replace("O", "0")
                .replace("D", "0")
                .replace("I", "1")
                .replace("L", "1")
                .replace("Z", "2")
                .replace("S", "5")
                .replace("G", "6")
                .replace("B", "8")
            )
            p_suffix_rep = p_suffix
            if p_suffix == "0":
                p_suffix_rep = "Q"
            elif p_suffix == "1":
                p_suffix_rep = "I"
            elif p_suffix == "5":
                p_suffix_rep = "S"
            elif p_suffix == "8":
                p_suffix_rep = "B"

            repaired = f"{p_prefix}{p_digits_rep}{p_suffix_rep}"
            if repaired == gt_pan:
                repairable_misread_confs.append((doc["id"], conf, raw_txt, gt_pan))
            else:
                unrepairable_confs.append((doc["id"], conf, raw_txt, gt_pan))

print(f"\nTotal PAN docs examined: {len(pan_docs)}")
print(f"Correctly read: {len(correct_confs)}")
print(f"Repairable misreads (confusable characters): {len(repairable_misread_confs)}")
print(f"Unrepairable misreads (severe crop/OCR garbage): {len(unrepairable_confs)}")

print("\nRepairable Misreads Confidences:")
rep_confs = [x[1] for x in repairable_misread_confs]
for item in repairable_misread_confs:
    print(f"  {item[0]}: GT={item[3]} RAW={item[2]} Conf={item[1]:.4f}")

corr_confs = [x[1] for x in correct_confs]
print(f"\nCorrect Confidences Stats: count={len(corr_confs)} min={min(corr_confs):.4f} mean={np.mean(corr_confs):.4f} median={np.median(corr_confs):.4f} max={max(corr_confs):.4f}")
print(f"Repairable Misread Stats: count={len(rep_confs)} min={min(rep_confs):.4f} mean={np.mean(rep_confs):.4f} median={np.median(rep_confs):.4f} max={max(rep_confs):.4f}")

# Threshold sweeps
print("\nThreshold Sweep Analysis:")
for th in [0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98]:
    repaired_count = sum(1 for c in rep_confs if c < th)
    pct = (repaired_count / len(rep_confs)) * 100 if rep_confs else 0
    print(f"  Threshold < {th:.2f}: Repairs {repaired_count}/{len(rep_confs)} ({pct:.1f}%) legitimate OCR confusions")
