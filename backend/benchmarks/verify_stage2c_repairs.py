"""
verify_stage2c_repairs.py - Verification of Character Repairs on Tampered Set
Tests:
1. Audits every character repair across all 40 tampered documents.
2. Checks whether any repair alters a tampered character or masks tampering.
3. Tests both with CONFIDENCE_REPAIR_THRESHOLD = 0.80 and without confidence gating (threshold = 1.0).
4. Produces the detailed audit log.
"""
import json
import os
import sys
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
from backend.modules.ocr_extraction.label_anchor import (
    OCRBox,
    extract_fields_cascade,
    boxes_from_raw_results,
    get_repair_audit_log,
    clear_repair_audit_log,
    CONFIDENCE_REPAIR_THRESHOLD,
)
import backend.modules.ocr_extraction.label_anchor as la

MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")


def main():
    print("=" * 110)
    print("STAGE 2c: VERIFY CHARACTER REPAIRS ON TAMPERED DOCUMENTS")
    print("=" * 110)

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    tampered_docs = [x for x in manifest if x.get("is_tampered", False)]
    print(f"Loaded {len(tampered_docs)} tampered documents.")

    reader = _easyocr_engine.get_reader("en")

    # Clear audit log
    clear_repair_audit_log()

    results = []

    for doc in tampered_docs:
        doc_id = doc["id"]
        doc_type = doc["document_type"]
        file_path = os.path.join(BASE_DIR, doc["file_path"])
        tamper_type = doc.get("tamper_type")
        tampered_field = doc.get("tampered_field")
        tamper_details = doc.get("tamper_details")
        gt = doc.get("ground_truth_fields", {})

        img = cv2.imread(file_path)
        if img is None:
            print(f"Could not load image: {file_path}")
            continue

        raw_results = reader.readtext(img)
        boxes = boxes_from_raw_results(raw_results, img.shape[:2])
        full_text = " ".join([b.text for b in boxes])

        # Run with current confidence gating (threshold = 0.80)
        la.CONFIDENCE_REPAIR_THRESHOLD = 0.80
        start_log_len = len(get_repair_audit_log())
        fields_gated, methods_gated = extract_fields_cascade(boxes, doc_type, full_text)
        new_repairs = get_repair_audit_log()[start_log_len:]

        # Run un-gated (threshold = 1.01) to see what un-gated repairs would do
        la.CONFIDENCE_REPAIR_THRESHOLD = 1.01
        dummy_log_start = len(la.REPAIR_AUDIT_LOG)
        fields_ungated, methods_ungated = extract_fields_cascade(boxes, doc_type, full_text)
        ungated_repairs = list(la.REPAIR_AUDIT_LOG[dummy_log_start:])
        # Remove dummy un-gated log entries from main audit log
        del la.REPAIR_AUDIT_LOG[dummy_log_start:]

        # Restore threshold
        la.CONFIDENCE_REPAIR_THRESHOLD = 0.80

        results.append({
            "id": doc_id,
            "doc_type": doc_type,
            "tamper_type": tamper_type,
            "tampered_field": tampered_field,
            "tamper_details": tamper_details,
            "gt": gt,
            "fields_gated": {k: v[0] for k, v in fields_gated.items()},
            "fields_ungated": {k: v[0] for k, v in fields_ungated.items()},
            "repairs_gated": new_repairs,
            "repairs_ungated": ungated_repairs,
        })

    print("\n" + "=" * 110)
    print("REPAIR AUDIT LOG ANALYSIS (ON 40 TAMPERED DOCUMENTS)")
    print("=" * 110)

    total_repairs_gated = sum(len(r["repairs_gated"]) for r in results)
    total_repairs_ungated = sum(len(r["repairs_ungated"]) for r in results)

    print(f"Repairs triggered with threshold < 0.80 (Active Gating): {total_repairs_gated}")
    print(f"Repairs triggered with threshold <= 1.00 (Un-gated Baseline): {total_repairs_ungated}")

    # Inspect every tampered document where tampering affected a text field
    text_tampered = [r for r in results if r["tamper_type"] in ("text_edit", "font_anomaly") or (r["tampered_field"] and r["tampered_field"] not in ("photo", "signature"))]

    print("\n--- DETAILED INSPECTION OF TEXT-TAMPERED DOCUMENTS ---")
    print(f"{'Doc ID':<30} | {'Tampered Field':<15} | {'Gated Value':<15} | {'Ungated Value':<15} | {'Masked?'}")
    print("-" * 110)

    masking_detected = False

    for r in text_tampered:
        tf = r["tampered_field"]
        gated_val = r["fields_gated"].get(tf, "NOT_EXTRACTED")
        ungated_val = r["fields_ungated"].get(tf, "NOT_EXTRACTED")
        gt_val = r["gt"].get(tf, "N/A")

        # Did gated repair change this field?
        repairs_on_tf = [rep for rep in r["repairs_gated"] if rep["field"] == tf]
        masked = False

        if repairs_on_tf:
            for rep in repairs_on_tf:
                if rep["repaired"] == gt_val and rep["original"] != gt_val:
                    masked = True
                    masking_detected = True

        print(f"{r['id']:<30} | {str(tf):<15} | {str(gated_val):<15} | {str(ungated_val):<15} | {str(masked)}")

    print("\n--- ALL REPAIRS LOGGED ON TAMPERED SET (Active Gating conf < 0.80) ---")
    if total_repairs_gated == 0:
        print("None! No repairs were applied to tampered documents under active confidence gating.")
    else:
        for r in results:
            for rep in r["repairs_gated"]:
                print(f"Doc: {r['id']} | Field: {rep['field']} | '{rep['original']}' -> '{rep['repaired']}' | Conf: {rep['confidence']} | Reason: {rep['reason']}")

    print("\n--- POTENTIAL TAMPERING MASKING IN UN-GATED (What gating prevented) ---")
    for r in results:
        for u_rep in r["repairs_ungated"]:
            is_tf = (u_rep["field"] == r["tampered_field"])
            was_suppressed = u_rep not in r["repairs_gated"]
            print(f"Doc: {r['id']} | Field: {u_rep['field']} (Tampered Field: {is_tf}) | '{u_rep['original']}' -> '{u_rep['repaired']}' | Conf: {u_rep['confidence']} | Suppressed by Gating: {was_suppressed}")

    print("\nSUMMARY:")
    print(f"Masking detected with gating: {masking_detected}")
    print("=" * 110)


if __name__ == "__main__":
    main()
