"""
inspect_stamp_module.py - Detailed diagnostic inspection of stamp_checker.py
Prints internal values for all 6 stamp_duplicate docs and 6 clean docs from the test dataset:
- upper_roi edge density
- match_score (template / ORB match)
- edge_regularity
- forgery_suspected
"""
import json
import os
import sys
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.tampering_detection.stamp_checker import check_stamp_seal, _get_reference_stamp, STAMPS_DIR

MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")


def inspect_stamp_module():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Pick all 6 stamp_duplicate documents
    stamp_tampered = [m for m in manifest if m["tamper_type"] == "stamp_duplicate"]
    
    # Pick 6 clean documents (2 PAN, 2 Aadhaar, 2 Voter)
    clean_pan = [m for m in manifest if m["document_type"] == "national_id_pan" and not m["is_tampered"]][:2]
    clean_aadhaar = [m for m in manifest if m["document_type"] == "national_id_aadhaar" and not m["is_tampered"]][:2]
    clean_voter = [m for m in manifest if m["document_type"] == "national_id_voter" and not m["is_tampered"]][:2]
    clean_docs = clean_pan + clean_aadhaar + clean_voter

    ref_stamp = _get_reference_stamp()
    ref_exists = os.path.exists(os.path.join(STAMPS_DIR, "reference_emblem.png"))
    print(f"Reference emblem file exists: {ref_exists} (path: {os.path.join(STAMPS_DIR, 'reference_emblem.png')})")
    print(f"Reference stamp loaded: {ref_stamp is not None}")

    print("\n" + "=" * 105)
    print(f"{'Doc ID':<30} | {'Type':<12} | {'ROI Shape':<12} | {'Edge Dens':<10} | {'Regularity':<10} | {'Match':<8} | {'Suspected':<10}")
    print("=" * 105)

    def analyze_doc(item):
        fpath = os.path.join(BASE_DIR, item["file_path"])
        img = cv2.imread(fpath)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h_img, w_img = gray.shape[:2]
        upper_roi = gray[0:int(h_img * 0.45), 0:int(w_img * 0.60)]
        edges = cv2.Canny(upper_roi, 80, 200)
        edge_density = float(np.count_nonzero(edges)) / float(upper_roi.size)

        res = check_stamp_seal(img)
        roi_shape_str = f"{upper_roi.shape[0]}x{upper_roi.shape[1]}"
        doc_label = "CLEAN" if not item["is_tampered"] else "STAMP_DUP"
        print(
            f"{item['id']:<30} | {doc_label:<12} | {roi_shape_str:<12} | "
            f"{edge_density:<10.4f} | {res.edge_regularity:<10.3f} | {res.match_score:<8.3f} | {str(res.forgery_suspected):<10}"
        )

    print("--- 6 CLEAN DOCUMENTS ---")
    for item in clean_docs:
        analyze_doc(item)

    print("\n--- 6 STAMP DUPLICATE DOCUMENTS ---")
    for item in stamp_tampered:
        analyze_doc(item)

    print("=" * 105)


if __name__ == "__main__":
    inspect_stamp_module()
