"""
benchmark_stage2_label_anchor.py - Stage 2 Evaluation Benchmark
Compares Baseline Parse Accuracy vs New Label-Anchored Parse Accuracy (Stage 2)
across all clean documents in manifest.json.
Reports extraction method per field: label_anchor, pattern_fallback, coordinate_template.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
from backend.modules.ocr_extraction.label_anchor import (
    OCRBox,
    extract_fields_cascade,
    boxes_from_raw_results,
)
from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.ocr_extraction.layout_templates import get_layout_template, crop_region

TEST_MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")
OUTPUT_JSON_PATH = os.path.join(BASE_DIR, "backend", "benchmarks", "stage2_evaluation_results.json")


def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]


def compute_cer(predicted: str, target: str) -> float:
    if not target or len(target) == 0:
        return 0.0
    dist = levenshtein_distance(predicted, target)
    return min(1.0, max(0.0, float(dist / len(target))))


def normalize_val(val: str, field_name: str) -> str:
    norm = str(val).strip().upper()
    if field_name in ("pan_number", "aadhaar_number", "epic_number", "passport_number", "visa_number"):
        norm = norm.replace(" ", "").replace("-", "")
    return norm


def main():
    print("=" * 105)
    print("STAGE 2 EVALUATION BENCHMARK: BASELINE PARSER VS LABEL-ANCHORED EXTRACTION")
    print("=" * 105)

    with open(TEST_MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    clean_docs = [x for x in manifest if not x.get("is_tampered", False)]
    print(f"Loaded {len(clean_docs)} clean evaluation documents across 5 types.")

    stats = defaultdict(lambda: defaultdict(lambda: {
        "total": 0,
        "old_exact": 0,
        "old_cer_sum": 0.0,
        "new_exact": 0,
        "new_cer_sum": 0.0,
        "methods": defaultdict(int),
    }))

    reader = _easyocr_engine.get_reader("en")
    t0 = time.perf_counter()

    for idx, doc in enumerate(clean_docs):
        file_path = os.path.join(BASE_DIR, doc["file_path"])
        doc_type = doc["document_type"]
        gt_fields = doc["ground_truth_fields"]

        img = cv2.imread(file_path)
        if img is None:
            continue

        h, w = img.shape[:2]

        # 1. Run EasyOCR to get raw bounding boxes
        raw_res = reader.readtext(img)
        boxes = boxes_from_raw_results(raw_res, img_shape=(h, w))
        full_text = "\n".join(b.text for b in boxes)

        # 2. Extract with Old Baseline Parser
        old_ocr_res = extract_ocr(file_path, doc_type)
        old_extracted = old_ocr_res.extracted_fields

        # 3. Extract with New Label-Anchored Cascade
        new_fields, new_methods = extract_fields_cascade(
            boxes,
            doc_type,
            full_text=full_text,
        )

        # Compare per field
        for f_name, gt_val in gt_fields.items():
            norm_gt = normalize_val(gt_val, f_name)
            if not norm_gt:
                continue

            # Evaluate Old Extracted
            cand_keys = [f_name]
            if f_name == "date_of_birth": cand_keys.extend(["dob", "birth_date"])
            elif f_name == "dob": cand_keys.extend(["date_of_birth"])
            elif f_name == "pan_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "aadhaar_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "epic_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "passport_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "visa_number": cand_keys.extend(["document_number", "id_number"])

            old_val = ""
            for ck in cand_keys:
                if ck in old_extracted and old_extracted[ck].value != "not applicable for this document type":
                    old_val = old_extracted[ck].value.strip()
                    break

            norm_old = normalize_val(old_val, f_name)
            old_cer = compute_cer(norm_old, norm_gt)
            old_match = (norm_old == norm_gt)

            # Evaluate New Extracted
            new_tuple = new_fields.get(f_name)
            if not new_tuple:
                # Aliases
                if f_name == "date_of_birth": new_tuple = new_fields.get("dob")
                elif f_name == "dob": new_tuple = new_fields.get("date_of_birth")

            new_val = new_tuple[0].strip() if new_tuple else ""
            norm_new = normalize_val(new_val, f_name)
            new_cer = compute_cer(norm_new, norm_gt)
            new_match = (norm_new == norm_gt)

            winning_method = new_methods.get(f_name, "none")
            if not winning_method or winning_method == "none":
                if f_name == "date_of_birth": winning_method = new_methods.get("dob", "none")

            # Record stats
            st = stats[doc_type][f_name]
            st["total"] += 1
            if old_match: st["old_exact"] += 1
            st["old_cer_sum"] += old_cer
            if new_match: st["new_exact"] += 1
            st["new_cer_sum"] += new_cer
            st["methods"][winning_method] += 1

    elapsed = time.perf_counter() - t0
    print(f"\nEvaluated {len(clean_docs)} clean docs in {elapsed:.2f} seconds.")

    # -----------------------------------------------------------------------
    # Print Comparison Table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 115)
    print("STAGE 2 BEFORE VS AFTER: PARSE ACCURACY PER FIELD & WINNING EXTRACTION METHOD")
    print("=" * 115)
    print(f"{'Doc Type':<18} | {'Field Name':<16} | {'Before Acc (CER)':<18} | {'After Acc (CER)':<18} | {'Primary Method':<18} | {'Status'}")
    print("-" * 115)

    report_json = {}

    for dt, f_dict in sorted(stats.items()):
        report_json[dt] = {}
        for f_name, st in sorted(f_dict.items()):
            n = st["total"]
            old_acc = (st["old_exact"] / n * 100.0) if n > 0 else 0.0
            old_cer = (st["old_cer_sum"] / n) if n > 0 else 0.0
            new_acc = (st["new_exact"] / n * 100.0) if n > 0 else 0.0
            new_cer = (st["new_cer_sum"] / n) if n > 0 else 0.0

            # Determine dominant winning method
            m_counts = st["methods"]
            top_m = max(m_counts.keys(), key=lambda k: m_counts[k]) if m_counts else "none"

            diff = new_acc - old_acc
            if diff > 0:
                status = f"+{diff:.1f}% GAIN"
            elif diff == 0:
                status = "UNCHANGED"
            else:
                status = f"{diff:.1f}%"

            print(f"{dt:<18} | {f_name:<16} | {old_acc:>5.1f}% ({old_cer:.2f})    | {new_acc:>5.1f}% ({new_cer:.2f})    | {top_m:<18} | {status}")
            report_json[dt][f_name] = {
                "n": n,
                "before_accuracy_pct": round(old_acc, 2),
                "before_cer": round(old_cer, 3),
                "after_accuracy_pct": round(new_acc, 2),
                "after_cer": round(new_cer, 3),
                "dominant_method": top_m,
                "method_counts": dict(m_counts),
            }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(report_json, f, indent=2)
    print(f"\nSaved Stage 2 evaluation results to: {OUTPUT_JSON_PATH}")


if __name__ == "__main__":
    main()
