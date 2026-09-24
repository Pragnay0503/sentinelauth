"""
calibrate_field_forensics.py - Runs field forensics across 150 clean calibration documents.
Records distribution of ela_anomaly_score and font_consistency_score per field.
Calculates 99th percentile of clean for ELA anomaly score and 1st percentile for font consistency score.
Saves calibrated thresholds to calibrated_thresholds.json.
"""
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.tampering_detection.field_forensics import analyze_all_document_fields

CALIB_MANIFEST = os.path.join(BASE_DIR, "data", "calibration_dataset", "manifest.json")
THRESHOLDS_JSON = os.path.join(BASE_DIR, "backend", "modules", "tampering_detection", "calibrated_thresholds.json")


def run_calibration():
    if not os.path.exists(CALIB_MANIFEST):
        raise FileNotFoundError(f"Calibration manifest not found at {CALIB_MANIFEST}")

    with open(CALIB_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"[Calibrate] Processing {len(manifest)} clean calibration documents...")

    # Data collector: (doc_type, field) -> list of (ela, font)
    stats: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(lambda: defaultdict(lambda: {"ela": [], "font": []}))

    for idx, item in enumerate(manifest, start=1):
        rel_path = item["file_path"]
        full_path = os.path.join(BASE_DIR, rel_path) if not os.path.isabs(rel_path) else rel_path
        doc_type = item["document_type"]

        img = cv2.imread(full_path)
        if img is None:
            print(f"Warning: could not read {full_path}")
            continue

        results = analyze_all_document_fields(img, document_type=doc_type)
        for field_name, res in results.items():
            stats[doc_type][field_name]["ela"].append(res.ela_anomaly_score)
            stats[doc_type][field_name]["font"].append(res.font_consistency_score)

        if idx % 25 == 0:
            print(f"  Processed {idx}/{len(manifest)} docs...")

    print("\n" + "=" * 105)
    print("CLEAN CALIBRATION DISTRIBUTION & PERCENTILES (REALISTIC PHYSICAL CAPTURE)")
    print("=" * 105)
    print(f"{'Doc Type':<22} | {'Field':<15} | {'ELA (Min / P50 / P99 / Max)':<30} | {'Font (P01 / P50 / Max)':<24} | {'Status':<15}")
    print("-" * 105)

    calibrated_thresholds: Dict[str, Dict[str, Dict[str, float]]] = {}

    for doc_type, fields in stats.items():
        calibrated_thresholds[doc_type] = {}
        for field_name, metric_dict in fields.items():
            ela_vals = np.array(metric_dict["ela"])
            font_vals = np.array(metric_dict["font"])

            ela_min = float(np.min(ela_vals))
            ela_med = float(np.median(ela_vals))
            ela_max = float(np.max(ela_vals))
            ela_p99 = float(np.percentile(ela_vals, 99))
            ela_std = float(np.std(ela_vals))

            font_min = float(np.min(font_vals))
            font_med = float(np.median(font_vals))
            font_max = float(np.max(font_vals))
            font_p01 = float(np.percentile(font_vals, 1))
            font_std = float(np.std(font_vals))

            # Near-constant check: variance near zero or max - min < 0.03
            is_near_constant = (ela_max - ela_min < 0.03) or (ela_std < 0.01)
            status_str = "NEAR-CONSTANT" if is_near_constant else "VARIED (OK)"

            ela_thresh = round(float(ela_p99), 3)
            font_thresh = round(float(font_p01), 3)

            calibrated_thresholds[doc_type][field_name] = {
                "ela_threshold_p99": ela_thresh,
                "font_threshold_p01": font_thresh,
                "ela_min": round(ela_min, 3),
                "ela_median": round(ela_med, 3),
                "ela_max": round(ela_max, 3),
                "ela_std": round(ela_std, 3),
                "font_median": round(font_med, 3),
                "font_min": round(font_min, 3),
                "font_p01": round(font_p01, 3),
                "font_std": round(font_std, 3),
                "is_near_constant": is_near_constant,
                "sample_count": len(ela_vals),
            }

            print(
                f"{doc_type:<22} | {field_name:<15} | "
                f"{ela_min:.2f} / {ela_med:.2f} / {ela_p99:.2f} / {ela_max:.2f} | "
                f"{font_p01:.2f} / {font_med:.2f} / {font_max:.2f}    | "
                f"{status_str:<15}"
            )

    # Save to JSON
    with open(THRESHOLDS_JSON, "w", encoding="utf-8") as f:
        json.dump(calibrated_thresholds, f, indent=2)

    print("\n" + "=" * 90)
    print(f"Calibrated thresholds saved to: {THRESHOLDS_JSON}")
    print("=" * 90)
    return calibrated_thresholds


if __name__ == "__main__":
    run_calibration()
