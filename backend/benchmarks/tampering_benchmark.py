"""
tampering_benchmark.py - Forensic Tampering Detection Precision, Recall & Threshold Sweep
with Full Localization Verification, Wilson 95% Confidence Intervals, and Diagnostics.

Evaluates detect_tampering on the synthetic dataset:
- Localization Verification: A detection counts as a TRUE POSITIVE only if at least one
  flagged region or field overlaps the real tampered region (IoU > 0.1 or field match).
  Detections for the wrong reason are categorized as WRONG-REASON flags.
- Statistical Rigor: Wilson score 95% confidence intervals and explicit sample sizes (n)
  reported next to all percentages.
- Breakdown by document type (PAN, Aadhaar, Voter ID) and tamper type.
- Full threshold sweep from 0 to 100 in steps of 10.
- Outputs detailed report to backend/benchmarks/tampering_results.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.tampering_detection.detector import detect_tampering
from backend.modules.tampering_detection.stamp_checker import check_stamp_seal
from backend.modules.ocr_extraction.layout_templates import get_layout_template

DEFAULT_MANIFEST = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")
OUTPUT_JSON = os.path.join(BASE_DIR, "backend", "benchmarks", "tampering_results.json")
DEFAULT_THRESHOLD = 0.40  # 40 on a 0-100 scale


def compute_iou(bbox1: Tuple[float, float, float, float], bbox2: Tuple[float, float, float, float]) -> float:
    """Computes Intersection-over-Union between two normalized bounding boxes [ymin, xmin, ymax, xmax]."""
    y1_min, x1_min, y1_max, x1_max = bbox1
    y2_min, x2_min, y2_max, x2_max = bbox2

    inter_ymin = max(y1_min, y2_min)
    inter_xmin = max(x1_min, x2_min)
    inter_ymax = min(y1_max, y2_max)
    inter_xmax = min(x1_max, x2_max)

    inter_w = max(0.0, inter_xmax - inter_xmin)
    inter_h = max(0.0, inter_ymax - inter_ymin)
    inter_area = inter_w * inter_h

    area1 = max(0.0, x1_max - x1_min) * max(0.0, y1_max - y1_min)
    area2 = max(0.0, x2_max - x2_min) * max(0.0, y2_max - y2_min)

    union = area1 + area2 - inter_area
    return float(inter_area / union) if union > 0.0 else 0.0


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Computes Wilson score 95% confidence interval for proportion k/n in percent [lower, upper]."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + (z ** 2) / n
    center = (p + (z ** 2) / (2.0 * n)) / denom
    margin = (z * ((p * (1.0 - p) / n + (z ** 2) / (4.0 * (n ** 2))) ** 0.5)) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (round(lower * 100, 1), round(upper * 100, 1))


def check_localization(item: Dict[str, Any], res: Any) -> Tuple[bool, str, List[str]]:
    """
    Determines whether a detection on a tampered document is for the correct reason,
    matching the ground truth tampered region (via IoU > 0.1 or field match).
    Returns (is_correct_reason, primary_reason_str, matched_details).
    """
    if not item.get("is_tampered"):
        return False, "clean_document", []

    t_op = item.get("tamper_type")
    t_field = item.get("tampered_field")
    t_bbox = item.get("tampered_bbox")
    doc_type = item.get("document_type")
    template = get_layout_template(doc_type) or {}

    matched_details = []

    # 1. Field Forensics check (text edits and stamp duplications placed inside field regions)
    flagged_fields = [f for f, r in res.field_forensics.items() if r.likely_tampered]
    for ff in flagged_fields:
        # Direct field name match
        if t_field and ff.lower() == t_field.lower():
            matched_details.append(f"field_match:{ff}")
        # IoU overlap between template bbox of flagged field and t_bbox
        if t_bbox and ff in template:
            f_bbox = template[ff]
            iou = compute_iou(tuple(f_bbox), tuple(t_bbox))
            if iou > 0.1:
                matched_details.append(f"field_iou_{iou:.2f}:{ff}")

    # 2. Photo region splicing check
    if t_op == "photo_swap":
        if (
            "SUSPECTED_PHOTO_SPLICING" in res.flagged_checks
            or res.photo_region.photo_splicing_detected
            or res.photo_region.ela_divergence >= 22.0
        ):
            matched_details.append("photo_splicing_detected")

    # 3. Whole-image recompression check
    if t_op == "recompression":
        if (
            "ELA_ANOMALY" in res.flagged_checks
            or res.ela.flagged
            or "HEAVY_RECOMPRESSION" in res.flagged_checks
        ):
            matched_details.append("global_recompression_detected")

    # 4. Stamp seal check
    if t_op == "stamp_duplicate":
        if (
            "IRREGULAR_EMBLEM_EDGES" in res.flagged_checks
            or res.stamp_seal.forgery_suspected
        ):
            matched_details.append("stamp_irregularity_detected")

    is_correct = len(matched_details) > 0
    reason_str = "; ".join(matched_details) if is_correct else "no_region_overlap"
    return is_correct, reason_str, matched_details


def compute_metrics(records: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """
    Computes rigorous classification metrics with localization categorization:
    - TP (Correct Reason): tampered & score >= threshold & overlaps tampered region
    - Wrong-Reason: tampered & score >= threshold & NO overlap with tampered region
    - FN (Missed): tampered & score < threshold
    - FP: clean & score >= threshold
    - TN: clean & score < threshold
    """
    tp_correct = 0
    wrong_reason = 0
    fn_missed = 0
    fp_clean = 0
    tn_clean = 0

    for r in records:
        gt = r["is_tampered"]
        pred = r["tampering_score"] >= threshold
        loc_correct = r.get("localization_correct", False)

        if gt:
            if pred:
                if loc_correct:
                    tp_correct += 1
                else:
                    wrong_reason += 1
            else:
                fn_missed += 1
        else:
            if pred:
                fp_clean += 1
            else:
                tn_clean += 1

    n_tampered = tp_correct + wrong_reason + fn_missed
    n_clean = fp_clean + tn_clean
    total_flagged = tp_correct + wrong_reason + fp_clean

    precision = round(tp_correct / total_flagged, 4) if total_flagged > 0 else None
    precision_pct = round(precision * 100, 1) if precision is not None else "N/A (no flags)"
    correct_recall = round(tp_correct / n_tampered, 4) if n_tampered > 0 else 0.0
    wrong_reason_rate = round(wrong_reason / n_tampered, 4) if n_tampered > 0 else 0.0
    missed_rate = round(fn_missed / n_tampered, 4) if n_tampered > 0 else 0.0
    fpr = round(fp_clean / n_clean, 4) if n_clean > 0 else 0.0
    f1 = (
        round(2 * precision * correct_recall / (precision + correct_recall), 4)
        if (precision is not None and (precision + correct_recall) > 0)
        else 0.0
    )

    prec_ci = wilson_ci(tp_correct, total_flagged) if total_flagged > 0 else "N/A (no flags)"
    rec_ci = wilson_ci(tp_correct, n_tampered)
    fpr_ci = wilson_ci(fp_clean, n_clean)

    return {
        "threshold": round(threshold * 100, 1),
        "threshold_normalized": round(threshold, 3),
        "tp_correct": tp_correct,
        "wrong_reason": wrong_reason,
        "fn_missed": fn_missed,
        "fp_clean": fp_clean,
        "tn_clean": tn_clean,
        "n_tampered": n_tampered,
        "n_clean": n_clean,
        "total_flagged": total_flagged,
        "precision": precision,
        "precision_pct": precision_pct,
        "precision_ci95": prec_ci,
        "correct_recall": correct_recall,
        "correct_recall_pct": round(correct_recall * 100, 1),
        "recall_ci95": rec_ci,
        "wrong_reason_rate_pct": round(wrong_reason_rate * 100, 1),
        "missed_rate_pct": round(missed_rate * 100, 1),
        "f1": f1,
        "f1_pct": round(f1 * 100, 1),
        "fpr": fpr,
        "fpr_pct": round(fpr * 100, 1),
        "fpr_ci95": fpr_ci,
    }


def _evaluate_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Evaluates a single document for forensic tampering (picklable for multiprocessing)."""
    doc_id = item["id"]
    rel_path = item["file_path"]
    full_path = os.path.join(BASE_DIR, rel_path) if not os.path.isabs(rel_path) else rel_path
    doc_type = item["document_type"]
    is_tampered = item["is_tampered"]
    tamper_type = item["tamper_type"]

    if not os.path.exists(full_path):
        return None

    with open(full_path, "rb") as f:
        img_bytes = f.read()

    t0 = time.perf_counter()
    res = detect_tampering(img_bytes, document_type=doc_type)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    loc_correct, loc_reason, loc_matches = check_localization(item, res)
    flagged_fields = [f for f, r in res.field_forensics.items() if r.likely_tampered]

    return {
        "id": doc_id,
        "document_type": doc_type,
        "is_tampered": is_tampered,
        "tamper_type": tamper_type,
        "tamper_variant": item.get("tamper_variant"),
        "tamper_details": item.get("tamper_details"),
        "tampered_field": item.get("tampered_field"),
        "tampered_bbox": item.get("tampered_bbox"),
        "tampering_score": res.tampering_score,
        "tampering_score_pct": round(res.tampering_score * 100, 1),
        "flagged_default": res.is_tampered,
        "localization_correct": loc_correct,
        "localization_reason": loc_reason,
        "localization_matches": loc_matches,
        "flagged_checks": res.flagged_checks,
        "flagged_fields": flagged_fields,
        "module_contributions": res.module_contributions,
        "latency_ms": latency_ms,
    }


def run_tampering_benchmark(
    manifest_path: str = DEFAULT_MANIFEST,
    quick: bool = False,
    workers: Optional[int] = None,
) -> Dict[str, Any]:
    print("=" * 86)
    print("SENTINELAUTH BENCHMARK: MODULE 3 FORENSIC TAMPERING DETECTION")
    print("=" * 86)

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found at {manifest_path}. Please run dataset_generator.py first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest: List[Dict[str, Any]] = json.load(f)

    if quick:
        # Quick 12-doc subset: 4 PAN, 4 Aadhaar, 4 Voter (2 clean, 2 tampered each)
        subset_manifest = []
        for dt in ["national_id_pan", "national_id_aadhaar", "national_id_voter"]:
            dt_clean = [d for d in manifest if d["document_type"] == dt and not d["is_tampered"]][:2]
            dt_tamp = [d for d in manifest if d["document_type"] == dt and d["is_tampered"]][:2]
            subset_manifest.extend(dt_clean + dt_tamp)
        manifest = subset_manifest
        print(f"Quick mode active: Evaluating {len(manifest)} document subset (4 per doc type).")
    else:
        # Full 48-doc benchmark for Indian IDs if evaluating the 48-doc baseline
        manifest_48 = [d for d in manifest if d["document_type"] in ("national_id_pan", "national_id_aadhaar", "national_id_voter")]
        if len(manifest_48) == 48:
            manifest = manifest_48
            print(f"Evaluating standard 48-document physical scan dataset (24 clean, 24 tampered).")
        else:
            print(f"Loaded {len(manifest)} evaluation documents from manifest.")

    num_workers = workers if workers is not None else max(1, (os.cpu_count() or 4) - 1)
    num_workers = min(num_workers, len(manifest))
    print(f"Executing with {num_workers} parallel worker processes (CPU count - 1)...")

    t_start = time.perf_counter()

    if num_workers > 1 and len(manifest) > 1:
        import concurrent.futures
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            raw_records = list(executor.map(_evaluate_item, manifest))
        records = [r for r in raw_records if r is not None]
    else:
        records = []
        for item in manifest:
            r = _evaluate_item(item)
            if r is not None:
                records.append(r)

    total_duration = time.perf_counter() - t_start

    for idx, r in enumerate(records, start=1):
        loc_str = f"LOC_OK [{r['localization_reason']}]" if (r["is_tampered"] and r["localization_correct"]) else ("LOC_FAIL" if r["is_tampered"] else "N/A")
        contrib_str = " ".join(f"{k[:4]}={v:.2f}" for k, v in r["module_contributions"].items() if v > 0) or "all_zero"
        print(f"[{idx:02d}/{len(records)}] {r['id']:<34} -> Score={r['tampering_score']:.3f} | Flag={r['flagged_default']:<5} | {loc_str:<32} | {contrib_str}")

    # 1. Performance at default threshold (0.40)
    default_metrics = compute_metrics(records, DEFAULT_THRESHOLD)

    # 2. Breakdown by document type
    doc_types = ["national_id_pan", "national_id_aadhaar", "national_id_voter"]
    doc_type_breakdown = {}
    for dt in doc_types:
        subset = [r for r in records if r["document_type"] == dt]
        m = compute_metrics(subset, DEFAULT_THRESHOLD)
        doc_type_breakdown[dt] = m

    # 3. Breakdown by tamper type (stamp_duplicate dropped from benchmark)
    tamper_types = ["photo_swap", "text_edit", "recompression"]
    tamper_type_breakdown = {}
    for tt in tamper_types:
        subset = [r for r in records if r["tamper_type"] == tt]
        detected_correct = [r for r in subset if r["tampering_score"] >= DEFAULT_THRESHOLD and r["localization_correct"]]
        wrong_flags = [r for r in subset if r["tampering_score"] >= DEFAULT_THRESHOLD and not r["localization_correct"]]
        missed = [r for r in subset if r["tampering_score"] < DEFAULT_THRESHOLD]
        total = len(subset)
        det_count = len(detected_correct)
        avg_score = round(sum(r["tampering_score"] for r in subset) / max(total, 1), 3)
        tamper_type_breakdown[tt] = {
            "total_samples": total,
            "correct_detected": det_count,
            "wrong_reason_flags": len(wrong_flags),
            "missed": len(missed),
            "detection_rate_pct": round((det_count / max(total, 1)) * 100, 1),
            "ci95": wilson_ci(det_count, total),
            "avg_score_pct": round(avg_score * 100, 1),
        }

    # 4. Module Contribution Analysis
    all_modules = ["ela", "photo", "exif", "text", "field_forensics"]
    module_totals = {m: 0.0 for m in all_modules}
    module_non_zero_counts = {m: 0 for m in all_modules}
    tamper_module_catches = {tt: {m: 0 for m in all_modules} for tt in tamper_types}

    for r in records:
        contribs = r.get("module_contributions", {})
        for m in all_modules:
            val = contribs.get(m, 0.0)
            module_totals[m] += val
            if val > 0.0:
                module_non_zero_counts[m] += 1
                if r["is_tampered"] and r.get("tamper_type"):
                    tamper_module_catches[r["tamper_type"]][m] += 1

    zero_contribution_modules = [m for m in all_modules if module_non_zero_counts[m] == 0]

    module_summary = {
        "module_totals": {k: round(v, 3) for k, v in module_totals.items()},
        "module_non_zero_counts": module_non_zero_counts,
        "tamper_module_catches": tamper_module_catches,
        "zero_contribution_modules": zero_contribution_modules,
    }

    stamp_diagnostics = []

    # 6. Full threshold sweep from 0 to 100 in steps of 10
    threshold_sweep = []
    best_f1 = -1.0
    optimal_step = None
    for t_step in range(0, 101, 10):
        t_val = t_step / 100.0
        m = compute_metrics(records, t_val)
        threshold_sweep.append(m)
        if t_val > 0:
            if m["f1"] > best_f1:
                best_f1 = m["f1"]
                optimal_step = m
            elif m["f1"] == best_f1 and optimal_step is not None:
                if m["fp_clean"] < optimal_step["fp_clean"] or (
                    m["fp_clean"] == optimal_step["fp_clean"]
                    and abs(t_val - DEFAULT_THRESHOLD) < abs(optimal_step["threshold_normalized"] - DEFAULT_THRESHOLD)
                ):
                    optimal_step = m

    benchmark_data = {
        "benchmark_name": "SentinelAuth Module 3 Forensic Tampering Detection Benchmark (Realistic Physical Capture)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disclaimer": "Benchmarked against synthetically generated documents and tampering, not real forged government documents (which cannot be legally sourced for testing).",
        "documents_evaluated": len(records),
        "clean_count": len([r for r in records if not r["is_tampered"]]),
        "tampered_count": len([r for r in records if r["is_tampered"]]),
        "default_threshold": round(DEFAULT_THRESHOLD * 100, 1),
        "default_metrics": default_metrics,
        "doc_type_breakdown": doc_type_breakdown,
        "tamper_type_breakdown": tamper_type_breakdown,
        "module_summary": module_summary,
        "stamp_diagnostics": stamp_diagnostics,
        "threshold_sweep": threshold_sweep,
        "optimal_threshold": optimal_step,
        "total_time_sec": round(total_duration, 2),
        "records": records,
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    # -----------------------------------------------------------------------
    # Console Output Reporting
    # -----------------------------------------------------------------------
    dm = default_metrics
    p_disp = f"{dm['precision_pct']}%" if isinstance(dm['precision_pct'], (int, float)) else str(dm['precision_pct'])
    p_ci_str = f"[{dm['precision_ci95'][0]}%, {dm['precision_ci95'][1]}%]" if isinstance(dm['precision_ci95'], (list, tuple)) else str(dm['precision_ci95'])

    print("\n" + "=" * 86)
    print("TAMPERING DETECTION BENCHMARK SUMMARY (REALISTIC PHYSICAL CAPTURE BASELINE)")
    print("=" * 86)
    print(f"Default Detection Threshold: {dm['threshold']}%*")
    print(f"Total Evaluated:             {len(records)} docs ({dm['n_clean']} clean, {dm['n_tampered']} tampered)*")
    print(f"Precision:                   {p_disp}* (95% CI: {p_ci_str}, n={dm['total_flagged']}) [TP={dm['tp_correct']}, FP={dm['fp_clean']}, WR={dm['wrong_reason']}]")
    print(f"Correct-Reason Recall:       {dm['correct_recall_pct']}%* (95% CI: [{dm['recall_ci95'][0]}%, {dm['recall_ci95'][1]}%], n={dm['n_tampered']}) [TP={dm['tp_correct']}, Missed={dm['fn_missed']}]")
    print(f"Wrong-Reason Flag Rate:      {dm['wrong_reason_rate_pct']}%* ({dm['wrong_reason']}/{dm['n_tampered']})")
    print(f"Missed (FN) Rate:            {dm['missed_rate_pct']}%* ({dm['fn_missed']}/{dm['n_tampered']})")
    print(f"F1 Score:                    {dm['f1_pct']}%*")
    print(f"False Positive Rate (FPR):   {dm['fpr_pct']}%* (95% CI: [{dm['fpr_ci95'][0]}%, {dm['fpr_ci95'][1]}%], n={dm['n_clean']}) [FP={dm['fp_clean']}/{dm['n_clean']}]")

    print("\nBreakdown by Document Type:")
    print(f"  {'Doc Type':<24} | {'Precision':<24} | {'Recall':<24} | {'FPR':<24}")
    print("  " + "-" * 100)
    for dt, b in doc_type_breakdown.items():
        if b['total_flagged'] > 0 and isinstance(b['precision_pct'], (int, float)):
            p_str = f"{b['precision_pct']}% [{b['precision_ci95'][0]}–{b['precision_ci95'][1]}%] (n={b['total_flagged']})"
        else:
            p_str = f"N/A (no flags) (n=0)"
        r_str = f"{b['correct_recall_pct']}% [{b['recall_ci95'][0]}–{b['recall_ci95'][1]}%] (n={b['n_tampered']})"
        f_str = f"{b['fpr_pct']}% [{b['fpr_ci95'][0]}–{b['fpr_ci95'][1]}%] (n={b['n_clean']})"
        print(f"  {dt:<24} | {p_str:<24} | {r_str:<24} | {f_str:<24}")

    print("\nBreakdown by Tamper Type:")
    print(f"  {'Tamper Type':<18} | {'Correct (TP)':<14} | {'Wrong-Reason':<14} | {'Missed (FN)':<14} | {'Detection Rate':<22}")
    print("  " + "-" * 90)
    for tt, b in tamper_type_breakdown.items():
        rate_str = f"{b['detection_rate_pct']}% [{b['ci95'][0]}–{b['ci95'][1]}%]"
        print(f"  {tt:<18} | {b['correct_detected']:>2}/{b['total_samples']:<11} | {b['wrong_reason_flags']:>2}/{b['total_samples']:<11} | {b['missed']:>2}/{b['total_samples']:<11} | {rate_str:<22}")

    print("\nModule Score Contributions Across All Documents:")
    print(f"  {'Module Name':<20} | {'Total Contrib':<15} | {f'Active Docs (n={len(records)})':<22} | {'Status':<15}")
    print("  " + "-" * 80)
    for m in all_modules:
        tot = module_totals[m]
        cnt = module_non_zero_counts[m]
        status = "INACTIVE (0.0)" if cnt == 0 else f"ACTIVE ({cnt}/{len(records)})"
        print(f"  {m:<20} | {tot:>13.3f}   | {cnt:>10} / {len(records)} docs | {status:<15}")

    print(f"\n  Modules contributing ZERO across all evaluated docs: {zero_contribution_modules}")

    print("\nModule Detection Attribution by Tamper Type:")
    print(f"  {'Tamper Type':<18} | {'Primary Module(s) Catching It'}")
    print("  " + "-" * 60)
    for tt, m_counts in tamper_module_catches.items():
        active = [f"{m} ({c} docs)" for m, c in m_counts.items() if c > 0]
        active_str = ", ".join(active) if active else "None (all missed by detector)"
        print(f"  {tt:<18} | {active_str}")

    print("\nNote: 'stamp_duplicate' has been dropped from the benchmark because without genuine card-issuer")
    print("reference emblem templates, stamp duplication cannot be verified reliably without severe false alarms.")

    print("\nThreshold Sweep (0 to 100 in steps of 10):")
    print("  Thresh | TP (Correct) | Wrong-Reason | Clean FP | Clean TN | Missed |   Precision   | Recall  |   F1   |")
    print("  -------+--------------+--------------+----------+----------+--------+---------------+---------+--------|")
    for s in threshold_sweep:
        if isinstance(s['precision_pct'], (int, float)):
            prec_str = f"{s['precision_pct']:>5.1f}%"
        else:
            prec_str = f"{s['precision_pct']:>13}"
        print(
            f"   {s['threshold']:>3.0f}%  |      {s['tp_correct']:>2}      |      {s['wrong_reason']:>2}      |    {s['fp_clean']:>2}    |    {s['tn_clean']:>2}    |   {s['fn_missed']:>2}   | {prec_str} |  {s['correct_recall_pct']:>5.1f}% |  {s['f1_pct']:>5.1f}% |"
        )

    opt_p_disp = f"{optimal_step['precision_pct']}%" if isinstance(optimal_step['precision_pct'], (int, float)) else str(optimal_step['precision_pct'])
    print(f"\nOptimal Threshold: {optimal_step['threshold']}%* (F1={optimal_step['f1_pct']}%, Precision={opt_p_disp}, Recall={optimal_step['correct_recall_pct']}%)")
    print("\n* Benchmarked against synthetically generated documents and tampering, not real forged government documents (which cannot be legally sourced for testing).")
    print(f"\nSaved detailed JSON to: {OUTPUT_JSON}")
    return benchmark_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SentinelAuth Module 3 Forensic Tampering Benchmark")
    parser.add_argument("--quick", action="store_true", help="Run 12-doc subset (4 PAN, 4 Aadhaar, 4 Voter) for rapid iteration")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel worker processes (default: CPU count - 1)")
    parser.add_argument("--manifest", type=str, default=DEFAULT_MANIFEST, help="Path to evaluation manifest")
    args = parser.parse_args()

    run_tampering_benchmark(manifest_path=args.manifest, quick=args.quick, workers=args.workers)
