"""
evaluate_clean_ocr.py - Evaluates OCR accuracy on all clean documents in the test and calibration sets.
Computes per-field exact match % and MRZ line exact match % vs known ground truth.
Reports single-document cold-cache latency.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.ocr_extraction.mrz_parser import _icao_checksum, detect_mrz_lines, parse_mrz_from_image

TEST_MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")
CALIB_MANIFEST_PATH = os.path.join(BASE_DIR, "data", "calibration_dataset", "manifest.json")
OUTPUT_REPORT_PATH = os.path.join(BASE_DIR, "backend", "benchmarks", "clean_ocr_accuracy_report.json")


def compute_expected_mrz(doc_type: str, gt: Dict[str, str]) -> Tuple[str, str]:
    """Computes the ground truth 44-char ICAO MRZ Line 1 and Line 2."""
    if doc_type == "passport":
        surname = gt.get("surname", "")
        given = gt.get("given_names", "")
        name_clean = f"{surname}<<{given.replace(' ', '<')}"
        l1 = (f"P<UTO{name_clean}" + "<" * 44)[:44]

        doc_num = (gt.get("passport_number", "") + "<" * 9)[:9]
        c_doc = str(_icao_checksum(doc_num))

        d_parts = gt.get("date_of_birth", "01/01/1980").split("/")
        dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
        c_dob = str(_icao_checksum(dob_yymmdd))

        e_parts = gt.get("date_of_expiry", "01/01/2030").split("/")
        exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
        c_exp = str(_icao_checksum(exp_yymmdd))

        opt = "<" * 14
        c_opt = "<"
        comp = str(_icao_checksum(doc_num + c_doc + dob_yymmdd + c_dob + exp_yymmdd + c_exp + opt + c_opt))
        l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{gt.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"
        return l1, l2

    elif doc_type == "visa":
        surname = gt.get("surname", "")
        given = gt.get("given_names", "")
        name_clean = f"{surname}<<{given.replace(' ', '<')}"
        l1 = (f"V<UTO{name_clean}" + "<" * 44)[:44]

        v_num = (gt.get("visa_number", "") + "<" * 9)[:9]
        c_vnum = str(_icao_checksum(v_num))

        d_parts = gt.get("date_of_birth", "01/01/1980").split("/")
        dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
        c_dob = str(_icao_checksum(dob_yymmdd))

        e_parts = gt.get("date_of_expiry", "01/01/2030").split("/")
        exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
        c_exp = str(_icao_checksum(exp_yymmdd))

        opt = "<" * 16
        l2 = f"{v_num}{c_vnum}UTO{dob_yymmdd}{c_dob}{gt.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}"
        return l1, l2

    return "", ""


def _eval_single_doc(item: Dict[str, Any]) -> Dict[str, Any]:
    file_path = os.path.join(BASE_DIR, item["file_path"]) if not os.path.isabs(item["file_path"]) else item["file_path"]
    doc_type = item["document_type"]
    gt = item["ground_truth_fields"]

    t0 = time.perf_counter()
    try:
        ocr_res = extract_ocr(file_path, doc_type)
        extracted = ocr_res.extracted_fields
        raw_text = ocr_res.raw_ocr_text
    except Exception as exc:
        print(f"Warning: OCR failed for {item['id']}: {exc}", flush=True)
        extracted = {}
        raw_text = ""
    elapsed = time.perf_counter() - t0

    # Field matching evaluation
    field_matches = {}
    for gt_field, gt_val in gt.items():
        cand_keys = [gt_field]
        if gt_field == "date_of_birth":
            cand_keys.extend(["dob", "birth_date"])
        elif gt_field == "dob":
            cand_keys.extend(["date_of_birth"])
        elif gt_field == "pan_number":
            cand_keys.extend(["document_number", "id_number"])
        elif gt_field == "aadhaar_number":
            cand_keys.extend(["document_number", "id_number"])
        elif gt_field == "epic_number":
            cand_keys.extend(["document_number", "id_number"])
        elif gt_field == "passport_number":
            cand_keys.extend(["document_number", "id_number"])
        elif gt_field == "visa_number":
            cand_keys.extend(["document_number", "id_number"])

        extracted_val = ""
        for ck in cand_keys:
            if ck in extracted and extracted[ck].value != "not applicable for this document type":
                extracted_val = extracted[ck].value.strip()
                break

        norm_gt = str(gt_val).strip().upper()
        norm_ext = str(extracted_val).strip().upper()
        if gt_field in ("aadhaar_number", "pan_number", "epic_number", "passport_number", "visa_number"):
            norm_gt = norm_gt.replace(" ", "")
            norm_ext = norm_ext.replace(" ", "")

        is_match = (norm_ext == norm_gt)
        field_matches[gt_field] = {
            "ground_truth": norm_gt,
            "extracted": norm_ext,
            "match": is_match,
        }

    # MRZ evaluation for passport and visa
    mrz_eval = None
    if doc_type in ("passport", "visa"):
        exp_l1, exp_l2 = compute_expected_mrz(doc_type, gt)
        candidate_lines = detect_mrz_lines(raw_text)
        cand_44 = [l.strip().replace(" ", "").upper() for l in candidate_lines if len(l.strip().replace(" ", "")) >= 36]

        matched_l1 = any(cand == exp_l1 for cand in cand_44)
        matched_l2 = any(cand == exp_l2 for cand in cand_44)

        actual_l1 = cand_44[0] if len(cand_44) > 0 else ""
        actual_l2 = cand_44[1] if len(cand_44) > 1 else ""

        mrz_eval = {
            "expected_line1": exp_l1,
            "actual_line1": actual_l1,
            "line1_exact_match": matched_l1,
            "expected_line2": exp_l2,
            "actual_line2": actual_l2,
            "line2_exact_match": matched_l2,
        }

    return {
        "id": item["id"],
        "document_type": doc_type,
        "elapsed_seconds": elapsed,
        "field_matches": field_matches,
        "mrz_eval": mrz_eval,
    }


def main():
    print("=" * 80)
    print("SENTINELAUTH CLEAN OCR ACCURACY BENCHMARK (PART 1)")
    print("=" * 80)

    # 1. Single-document Cold-Cache Latency Measurement
    print("\n[Stage 1] Measuring Single-Document COLD-CACHE OCR Latency...")
    test_clean = json.load(open(TEST_MANIFEST_PATH))
    clean_sample = [x for x in test_clean if not x.get("is_tampered", False)][0]
    sample_path = os.path.join(BASE_DIR, clean_sample["file_path"])
    
    from backend.modules.ocr_extraction.extractor import OCR_CACHE_DIR
    import hashlib
    with open(sample_path, "rb") as f:
        bytes_data = f.read()
    h = hashlib.sha256(bytes_data)
    h.update(str(clean_sample["document_type"]).encode("utf-8"))
    cache_f = os.path.join(OCR_CACHE_DIR, f"{h.hexdigest()}.json")
    if os.path.exists(cache_f):
        os.remove(cache_f)

    t_cold_start = time.perf_counter()
    res_cold = extract_ocr(sample_path, clean_sample["document_type"])
    cold_latency = time.perf_counter() - t_cold_start
    print(f"Cold-Cache OCR Latency for {clean_sample['id']}: {cold_latency:.3f} seconds.")

    # 2. Gather All Clean Documents from Test and Calibration Sets
    all_clean: List[Dict[str, Any]] = []
    with open(TEST_MANIFEST_PATH, "r", encoding="utf-8") as f:
        m_test = json.load(f)
        clean_test = [x for x in m_test if not x.get("is_tampered", False)]
        all_clean.extend(clean_test)
        print(f"Loaded {len(clean_test)} clean test documents.")

    with open(CALIB_MANIFEST_PATH, "r", encoding="utf-8") as f:
        m_calib = json.load(f)
        clean_calib = [x for x in m_calib if not x.get("is_tampered", False)]
        all_clean.extend(clean_calib)
        print(f"Loaded {len(clean_calib)} clean calibration documents.")

    total_clean_count = len(all_clean)
    print(f"Total clean documents to evaluate: {total_clean_count}")

    # 3. Parallel Execution across workers (capped to 3 to prevent memory exhaustion with heavy OCR models)
    workers = 3
    print(f"\n[Stage 2] Running OCR evaluation using {workers} parallel worker processes...", flush=True)
    t_eval_start = time.perf_counter()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_eval_single_doc, all_clean))

    total_eval_time = time.perf_counter() - t_eval_start
    print(f"Completed evaluation of {total_clean_count} documents in {total_eval_time:.2f} seconds ({total_eval_time/total_clean_count:.2f}s / doc parallel).")

    # 4. Aggregate Metrics
    stats_by_type = defaultdict(lambda: {"count": 0, "fields": defaultdict(lambda: {"total": 0, "correct": 0})})
    mrz_stats = defaultdict(lambda: {"count": 0, "line1_correct": 0, "line2_correct": 0, "both_correct": 0})

    for r in results:
        dt = r["document_type"]
        stats_by_type[dt]["count"] += 1
        for f_name, f_data in r["field_matches"].items():
            stats_by_type[dt]["fields"][f_name]["total"] += 1
            if f_data["match"]:
                stats_by_type[dt]["fields"][f_name]["correct"] += 1

        if r["mrz_eval"] is not None:
            mrz_stats[dt]["count"] += 1
            l1_ok = r["mrz_eval"]["line1_exact_match"]
            l2_ok = r["mrz_eval"]["line2_exact_match"]
            if l1_ok:
                mrz_stats[dt]["line1_correct"] += 1
            if l2_ok:
                mrz_stats[dt]["line2_correct"] += 1
            if l1_ok and l2_ok:
                mrz_stats[dt]["both_correct"] += 1

    # Print Summary Tables
    print("\n" + "=" * 80)
    print("PER-FIELD OCR EXACT-MATCH ACCURACY SUMMARY (CLEAN DOCUMENTS)")
    print("=" * 80)
    print(f"{'Doc Type':<22} | {'Field Name':<22} | {'Exact Matches':<15} | {'Accuracy %':<10} | {'Status (<95% flag)'}")
    print("-" * 80)

    any_below_95 = False
    failing_fields = []

    report_data = {
        "cold_cache_latency_seconds": round(cold_latency, 3),
        "total_clean_documents": total_clean_count,
        "evaluation_time_seconds": round(total_eval_time, 2),
        "doc_type_field_accuracy": {},
        "mrz_line_accuracy": {},
        "failing_fields_below_95": [],
    }

    for dt, data in sorted(stats_by_type.items()):
        report_data["doc_type_field_accuracy"][dt] = {}
        for f_name, counts in sorted(data["fields"].items()):
            tot = counts["total"]
            corr = counts["correct"]
            acc = (corr / tot * 100.0) if tot > 0 else 0.0
            is_failing = acc < 95.0
            if is_failing:
                any_below_95 = True
                failing_fields.append(f"{dt}.{f_name} ({acc:.1f}%)")
            flag_str = "FAIL (< 95%)" if is_failing else "PASS"
            print(f"{dt:<22} | {f_name:<22} | {corr:>5}/{tot:<7} | {acc:>8.2f}% | {flag_str}")
            report_data["doc_type_field_accuracy"][dt][f_name] = {
                "correct": corr,
                "total": tot,
                "accuracy_pct": round(acc, 2),
                "pass_95": not is_failing,
            }

    print("\n" + "=" * 80)
    print("MRZ LINE ACCURACY SUMMARY (EXACT 44-CHAR LINE MATCH)")
    print("=" * 80)
    print(f"{'Doc Type':<12} | {'Samples':<8} | {'Line 1 (44c) %':<16} | {'Line 2 (44c) %':<16} | {'Both Lines %':<14} | {'Status'}")
    print("-" * 80)

    for dt, m_data in sorted(mrz_stats.items()):
        cnt = m_data["count"]
        l1_pct = (m_data["line1_correct"] / cnt * 100.0) if cnt > 0 else 0.0
        l2_pct = (m_data["line2_correct"] / cnt * 100.0) if cnt > 0 else 0.0
        both_pct = (m_data["both_correct"] / cnt * 100.0) if cnt > 0 else 0.0
        mrz_fail = l1_pct < 95.0 or l2_pct < 95.0
        if mrz_fail:
            any_below_95 = True
            failing_fields.append(f"{dt}.mrz_lines (L1={l1_pct:.1f}%, L2={l2_pct:.1f}%)")
        status_str = "FAIL (< 95%)" if mrz_fail else "PASS"
        print(f"{dt:<12} | {cnt:<8} | {m_data['line1_correct']:>3}/{cnt} ({l1_pct:5.1f}%) | {m_data['line2_correct']:>3}/{cnt} ({l2_pct:5.1f}%) | {m_data['both_correct']:>3}/{cnt} ({both_pct:5.1f}%) | {status_str}")
        report_data["mrz_line_accuracy"][dt] = {
            "samples": cnt,
            "line1_accuracy_pct": round(l1_pct, 2),
            "line2_accuracy_pct": round(l2_pct, 2),
            "both_lines_accuracy_pct": round(both_pct, 2),
            "pass_95": not mrz_fail,
        }

    report_data["failing_fields_below_95"] = failing_fields
    with open(OUTPUT_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"\nDetailed report saved to: {OUTPUT_REPORT_PATH}")

    print("\n" + "=" * 80)
    if any_below_95:
        print("ALERT: One or more fields / MRZ lines scored BELOW 95% accuracy.")
        print(f"Failing components: {failing_fields}")
    else:
        print("ALL fields and MRZ lines achieved >= 95% accuracy!")
    print("=" * 80)


if __name__ == "__main__":
    main()
