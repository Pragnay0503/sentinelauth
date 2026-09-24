"""
diagnose_recognition_vs_parsing.py - Stage 1 Diagnostic Benchmark (Refined)
Measures Raw Character Accuracy (CER on cropped field regions) vs Current Parse Accuracy
Classifies each failure as:
  - PARSING FAILURE (OCR sees text, parser fails)
  - CROPPING FAILURE (Template bbox misaligned / broken crop / watermark overlap)
  - RECOGNITION FAILURE (OCR misreads characters)
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.ocr_extraction.layout_templates import get_layout_template, crop_region
from backend.modules.ocr_extraction.ocr_engine import extract_raw_text
from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.ocr_extraction.mrz_parser import detect_mrz_lines, _icao_checksum

TEST_MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")
OUTPUT_JSON_PATH = os.path.join(BASE_DIR, "backend", "benchmarks", "stage1_diagnosis_results.json")


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
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
    """Computes Character Error Rate strictly clipped to [0.0, 1.0]. Skips empty truth."""
    if not target or len(target) == 0:
        return 0.0
    dist = levenshtein_distance(predicted, target)
    return min(1.0, max(0.0, float(dist / len(target))))


def normalize_val(val: str, field_name: str) -> str:
    """Standardizes string comparison."""
    norm = str(val).strip().upper()
    if field_name in ("pan_number", "aadhaar_number", "epic_number", "passport_number", "visa_number"):
        norm = norm.replace(" ", "").replace("-", "")
    return norm


def find_best_candidate_in_crop(crop_text: str, target: str, field_name: str) -> Tuple[str, float]:
    """
    Finds the token or candidate sequence in the crop that best matches the ground truth target.
    Eliminates label noise from distorting raw character accuracy.
    """
    norm_target = normalize_val(target, field_name)
    norm_crop = normalize_val(crop_text, field_name)

    if not norm_target:
        return "", 0.0

    # 1. Exact substring match
    if norm_target in norm_crop:
        return norm_target, 0.0

    # 2. Token-level best match
    tokens = [normalize_val(t, field_name) for t in crop_text.split() if t.strip()]
    if not tokens:
        return "", 1.0

    best_cand = tokens[0]
    best_cer = compute_cer(best_cand, norm_target)

    # Single token search
    for tok in tokens:
        cer = compute_cer(tok, norm_target)
        if cer < best_cer:
            best_cer = cer
            best_cand = tok

    # Multi-token window search for multi-word fields (e.g. names)
    target_words = norm_target.split()
    if len(target_words) > 1:
        w_len = len(target_words)
        for i in range(len(tokens) - w_len + 1):
            window_str = " ".join(tokens[i:i + w_len])
            cer = compute_cer(window_str, norm_target)
            if cer < best_cer:
                best_cer = cer
                best_cand = window_str

    return best_cand, best_cer


def main():
    print("=" * 80)
    print("STAGE 1: DIAGNOSE RECOGNITION VS PARSING VS CROPPING FAILURES")
    print("=" * 80)

    with open(TEST_MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    clean_docs = [x for x in manifest if not x.get("is_tampered", False)]
    print(f"Loaded {len(clean_docs)} clean evaluation documents across 5 types.")

    field_stats = defaultdict(lambda: defaultdict(lambda: {
        "total": 0,
        "raw_exact": 0,
        "raw_cer_sum": 0.0,
        "parse_exact": 0,
        "parse_cer_sum": 0.0,
        "has_template_bbox": True,
    }))

    mrz_stats = defaultdict(lambda: {
        "total": 0,
        "raw_l1_exact": 0, "raw_l1_cer": 0.0,
        "raw_l2_exact": 0, "raw_l2_cer": 0.0,
        "parse_l1_exact": 0, "parse_l2_exact": 0,
    })

    t0 = time.perf_counter()

    for idx, doc in enumerate(clean_docs):
        file_path = os.path.join(BASE_DIR, doc["file_path"])
        doc_type = doc["document_type"]
        gt_fields = doc["ground_truth_fields"]

        img = cv2.imread(file_path)
        if img is None:
            continue

        template = get_layout_template(doc_type) or {}
        parsed_res = extract_ocr(file_path, doc_type)
        ext_fields = parsed_res.extracted_fields
        raw_full_text = parsed_res.raw_ocr_text

        for f_name, gt_val in gt_fields.items():
            norm_gt = normalize_val(gt_val, f_name)
            if not norm_gt:
                continue

            # 1. Raw Character Accuracy on Cropped Region
            crop_key = f_name
            if f_name == "date_of_birth": crop_key = "dob"
            elif f_name == "date_of_expiry": crop_key = "expiry"

            bbox = template.get(crop_key)
            has_bbox = bool(bbox)

            if bbox:
                crop, _ = crop_region(img, bbox, padding=0.01)
                crop_raw_text, _ = extract_raw_text(crop)
                cand_val, raw_cer = find_best_candidate_in_crop(crop_raw_text, norm_gt, f_name)
            else:
                # If no template bbox defined in layout_templates.py, probe full page OCR text
                has_bbox = False
                cand_val, raw_cer = find_best_candidate_in_crop(raw_full_text, norm_gt, f_name)

            raw_cer = min(1.0, max(0.0, raw_cer))
            raw_match = (cand_val == norm_gt)

            # 2. Parsed Field Value from Current Extractor
            cand_keys = [f_name]
            if f_name == "date_of_birth": cand_keys.extend(["dob", "birth_date"])
            elif f_name == "dob": cand_keys.extend(["date_of_birth"])
            elif f_name == "pan_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "aadhaar_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "epic_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "passport_number": cand_keys.extend(["document_number", "id_number"])
            elif f_name == "visa_number": cand_keys.extend(["document_number", "id_number"])

            parsed_val = ""
            for ck in cand_keys:
                if ck in ext_fields and ext_fields[ck].value != "not applicable for this document type":
                    parsed_val = ext_fields[ck].value.strip()
                    break

            norm_parsed = normalize_val(parsed_val, f_name)
            parse_cer = compute_cer(norm_parsed, norm_gt)
            parse_match = (norm_parsed == norm_gt)

            # Record stats
            st = field_stats[doc_type][f_name]
            st["total"] += 1
            st["has_template_bbox"] = st["has_template_bbox"] and has_bbox
            if raw_match: st["raw_exact"] += 1
            st["raw_cer_sum"] += raw_cer
            if parse_match: st["parse_exact"] += 1
            st["parse_cer_sum"] += parse_cer

        # MRZ evaluation for passport and visa
        if doc_type in ("passport", "visa"):
            surname = gt_fields.get("surname", "")
            given = gt_fields.get("given_names", "")
            name_clean = f"{surname}<<{given.replace(' ', '<')}"
            prefix = "P<UTO" if doc_type == "passport" else "V<UTO"
            exp_l1 = (f"{prefix}{name_clean}" + "<" * 44)[:44]

            doc_k = "passport_number" if doc_type == "passport" else "visa_number"
            doc_num = (gt_fields.get(doc_k, "") + "<" * 9)[:9]
            c_doc = str(_icao_checksum(doc_num))
            d_parts = gt_fields.get("date_of_birth", "01/01/1980").split("/")
            dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
            c_dob = str(_icao_checksum(dob_yymmdd))
            e_parts = gt_fields.get("date_of_expiry", "01/01/2030").split("/")
            exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
            c_exp = str(_icao_checksum(exp_yymmdd))
            if doc_type == "passport":
                opt = "<" * 14; c_opt = "<"
                comp = str(_icao_checksum(doc_num + c_doc + dob_yymmdd + c_dob + exp_yymmdd + c_exp + opt + c_opt))
                exp_l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{gt_fields.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"
            else:
                opt = "<" * 16
                exp_l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{gt_fields.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}"

            m_crop, _ = crop_region(img, (0.80, 0.0, 1.0, 1.0), padding=0.0)
            m_text, _ = extract_raw_text(m_crop)
            cands = [l.strip().replace(" ", "").upper() for l in m_text.splitlines() if len(l.strip().replace(" ", "")) >= 36]
            if not cands:
                cands = [l.strip().replace(" ", "").upper() for l in detect_mrz_lines(raw_full_text) if len(l.strip().replace(" ", "")) >= 36]

            act_l1 = cands[0] if len(cands) > 0 else ""
            act_l2 = cands[1] if len(cands) > 1 else ""

            m_st = mrz_stats[doc_type]
            m_st["total"] += 1
            if act_l1 == exp_l1: m_st["raw_l1_exact"] += 1
            m_st["raw_l1_cer"] += compute_cer(act_l1, exp_l1)
            if act_l2 == exp_l2: m_st["raw_l2_exact"] += 1
            m_st["raw_l2_cer"] += compute_cer(act_l2, exp_l2)

    elapsed_diag = time.perf_counter() - t0
    print(f"\nDiagnosis completed in {elapsed_diag:.2f} seconds.")

    # -----------------------------------------------------------------------
    # Print Diagnostics Table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("STAGE 1 DIAGNOSTIC REPORT: RECOGNITION ACCURACY VS PARSING ACCURACY (CORRECTED CER)")
    print("=" * 105)
    print(f"{'Doc Type':<18} | {'Field Name':<16} | {'Raw Char Acc % (CER)':<23} | {'Parse Acc %':<12} | {'Failure Classification'}")
    print("-" * 105)

    results_out = {"fields": {}, "mrz": {}}

    for dt, f_dict in sorted(field_stats.items()):
        results_out["fields"][dt] = {}
        for f_name, st in sorted(f_dict.items()):
            n = st["total"]
            raw_acc = (st["raw_exact"] / n * 100.0) if n > 0 else 0.0
            avg_raw_cer = min(1.0, max(0.0, st["raw_cer_sum"] / n)) if n > 0 else 0.0
            raw_char_acc = max(0.0, 1.0 - avg_raw_cer) * 100.0

            parse_acc = (st["parse_exact"] / n * 100.0) if n > 0 else 0.0
            avg_parse_cer = min(1.0, max(0.0, st["parse_cer_sum"] / n)) if n > 0 else 0.0

            has_bbox = st["has_template_bbox"]

            # Classification logic per instructions
            if parse_acc >= 95.0:
                classification = "PASS"
            elif not has_bbox or (raw_char_acc < parse_acc) or (f_name in ("sex", "date_of_expiry", "valid_from") and raw_char_acc < 85.0 and f_name in dt):
                classification = "CROPPING FAILURE (Template offset / missing box)"
            elif raw_char_acc >= 85.0 and parse_acc < raw_char_acc:
                classification = "PARSING FAILURE (OCR sees text, parser fails)"
            elif raw_char_acc < 85.0:
                classification = "RECOGNITION FAILURE (OCR misreads chars)"
            else:
                classification = "PARSING FAILURE (OCR sees text, parser fails)"

            print(f"{dt:<18} | {f_name:<16} | {raw_char_acc:>5.1f}% (CER {avg_raw_cer:.2f})  | {parse_acc:>6.1f}%     | {classification}")
            results_out["fields"][dt][f_name] = {
                "n": n,
                "raw_char_accuracy_pct": round(raw_char_acc, 2),
                "raw_cer": round(avg_raw_cer, 3),
                "parse_accuracy_pct": round(parse_acc, 2),
                "parse_cer": round(avg_parse_cer, 3),
                "classification": classification,
            }

    print("\n" + "=" * 105)
    print("MRZ LINES DIAGNOSTIC (PASSPORT & VISA)")
    print("=" * 105)
    print(f"{'Doc Type':<12} | {'Line':<8} | {'Raw Char Acc % (CER)':<23} | {'Exact Match %':<14} | {'Failure Classification'}")
    print("-" * 105)

    for dt, m_st in sorted(mrz_stats.items()):
        results_out["mrz"][dt] = {}
        n = m_st["total"]
        l1_cer = min(1.0, max(0.0, m_st["raw_l1_cer"] / n)) if n > 0 else 0.0
        l2_cer = min(1.0, max(0.0, m_st["raw_l2_cer"] / n)) if n > 0 else 0.0
        l1_char_acc = max(0.0, 1.0 - l1_cer) * 100.0
        l2_char_acc = max(0.0, 1.0 - l2_cer) * 100.0
        l1_exact = (m_st["raw_l1_exact"] / n * 100.0) if n > 0 else 0.0
        l2_exact = (m_st["raw_l2_exact"] / n * 100.0) if n > 0 else 0.0

        print(f"{dt:<12} | Line 1   | {l1_char_acc:>5.1f}% (CER {l1_cer:.2f})  | {l1_exact:>6.1f}%       | RECOGNITION (0/O, 1/I, < OCR-B confusion)")
        print(f"{dt:<12} | Line 2   | {l2_char_acc:>5.1f}% (CER {l2_cer:.2f})  | {l2_exact:>6.1f}%       | RECOGNITION (digit/letter confusion)")

        results_out["mrz"][dt] = {
            "n": n,
            "line1": {"char_acc": round(l1_char_acc, 2), "cer": round(l1_cer, 3), "exact_pct": round(l1_exact, 2)},
            "line2": {"char_acc": round(l2_char_acc, 2), "cer": round(l2_cer, 3), "exact_pct": round(l2_exact, 2)},
        }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(results_out, f, indent=2)
    print(f"\nSaved refined diagnosis results to: {OUTPUT_JSON_PATH}")


if __name__ == "__main__":
    main()
