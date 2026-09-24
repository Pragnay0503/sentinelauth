"""
ocr_benchmark.py - Accuracy & Character Error Rate (CER) Benchmark for Module 1 OCR.

Evaluates extract_ocr on the synthetic dataset (clean & tampered):
- Per-field exact-match accuracy (%)
- Character Error Rate (Levenshtein-based) against ground_truth_fields
- Breakdown by document type (PAN vs Aadhaar vs Voter ID)
- Identifies the 5 worst-performing images/fields
- Outputs JSON report to backend/benchmarks/ocr_results.json + markdown summary
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.ocr_extraction.ocr_engine import init_ocr_engine

DEFAULT_MANIFEST = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")
OUTPUT_JSON = os.path.join(BASE_DIR, "backend", "benchmarks", "ocr_results.json")


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes exact Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row
    return prev_row[-1]


def calculate_cer(reference: str, hypothesis: str) -> float:
    """
    Character Error Rate = Levenshtein_distance(ref, hyp) / max(len(ref), 1).
    """
    ref = reference.strip()
    hyp = hypothesis.strip()
    if not ref:
        return 0.0 if not hyp else 1.0
    dist = levenshtein_distance(ref, hyp)
    return round(dist / len(ref), 4)


def normalize_val(v: Any) -> str:
    """Standardizes string values for robust, fair comparison."""
    if v is None:
        return ""
    s = str(v).strip().upper()
    # Normalize common date representations
    # e.g., 1985-04-12 -> 12/04/1985
    m_iso = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", s)
    if m_iso:
        s = f"{m_iso.group(3)}/{m_iso.group(2)}/{m_iso.group(1)}"
    # Collapse multiple whitespaces
    s = re.sub(r"\s+", " ", s)
    return s


def is_field_match(gt_val: str, ext_val: str, field_name: str) -> Tuple[bool, float]:
    """
    Checks if extracted field matches ground truth, computing exact-match boolean and CER.
    """
    gt_norm = normalize_val(gt_val)
    ext_norm = normalize_val(ext_val)

    if not gt_norm and not ext_norm:
        return True, 0.0

    # Specific normalization for Aadhaar numbers (with or without spaces)
    if "aadhaar" in field_name:
        gt_clean = gt_norm.replace(" ", "")
        ext_clean = ext_norm.replace(" ", "")
        if gt_clean == ext_clean:
            return True, 0.0
        return False, calculate_cer(gt_clean, ext_clean)

    # General exact match
    if gt_norm == ext_norm:
        return True, 0.0

    cer = calculate_cer(gt_norm, ext_norm)
    return False, cer


def run_ocr_benchmark(manifest_path: str = DEFAULT_MANIFEST) -> Dict[str, Any]:
    print("=" * 78)
    print("SENTINELAUTH BENCHMARK: MODULE 1 OCR EXTRACTION ACCURACY & CER")
    print("=" * 78)

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found at {manifest_path}. Please run dataset_generator.py first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest: List[Dict[str, Any]] = json.load(f)

    print(f"Loaded {len(manifest)} evaluation documents from manifest.")
    print("Pre-warming neural OCR singleton...")
    init_ocr_engine()

    total_fields = 0
    exact_matches = 0
    cer_sum = 0.0

    # Per-doc type statistics
    doc_type_stats: Dict[str, Dict[str, Any]] = {
        "national_id_pan": {"total_fields": 0, "exact_matches": 0, "cer_sum": 0.0, "doc_count": 0},
        "national_id_aadhaar": {"total_fields": 0, "exact_matches": 0, "cer_sum": 0.0, "doc_count": 0},
        "national_id_voter": {"total_fields": 0, "exact_matches": 0, "cer_sum": 0.0, "doc_count": 0},
    }

    field_error_log: List[Dict[str, Any]] = []
    doc_evaluations: List[Dict[str, Any]] = []

    t_start_all = time.perf_counter()

    for idx, item in enumerate(manifest, start=1):
        doc_id = item["id"]
        rel_path = item["file_path"]
        full_path = os.path.join(BASE_DIR, rel_path) if not os.path.isabs(rel_path) else rel_path
        doc_type = item["document_type"]
        gt_fields: Dict[str, str] = item["ground_truth_fields"]

        if not os.path.exists(full_path):
            print(f"[{idx}/{len(manifest)}] Missing file: {full_path}")
            continue

        with open(full_path, "rb") as f:
            front_bytes = f.read()

        t0 = time.perf_counter()
        ocr_result = extract_ocr(front_bytes, document_type=doc_type)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        extracted_map = {k: v.value for k, v in ocr_result.extracted_fields.items()}

        doc_exact = 0
        doc_fields = len(gt_fields)
        doc_cer_sum = 0.0
        doc_field_comparisons = {}

        stats_bucket = doc_type_stats.get(doc_type)
        if stats_bucket:
            stats_bucket["doc_count"] += 1

        for f_name, gt_val in gt_fields.items():
            # Match field or common alias
            ext_val = extracted_map.get(f_name)
            if ext_val is None:
                # Check aliases
                if f_name in ("pan_number", "aadhaar_number", "epic_number"):
                    ext_val = extracted_map.get("document_number", "")
                elif f_name == "date_of_birth":
                    ext_val = extracted_map.get("dob", "")
                else:
                    ext_val = ""

            # Filter placeholder text
            if ext_val in ("not applicable for this document type", "None", None):
                ext_val = ""

            match, cer = is_field_match(gt_val, ext_val, f_name)

            total_fields += 1
            cer_sum += cer
            doc_cer_sum += cer

            if stats_bucket:
                stats_bucket["total_fields"] += 1
                stats_bucket["cer_sum"] += cer

            if match:
                exact_matches += 1
                doc_exact += 1
                if stats_bucket:
                    stats_bucket["exact_matches"] += 1
            else:
                field_error_log.append({
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "is_tampered": item["is_tampered"],
                    "tamper_type": item["tamper_type"],
                    "field_name": f_name,
                    "ground_truth": gt_val,
                    "extracted": ext_val,
                    "cer": cer,
                })

            doc_field_comparisons[f_name] = {
                "ground_truth": gt_val,
                "extracted": ext_val,
                "exact_match": match,
                "cer": cer,
            }

        doc_evaluations.append({
            "id": doc_id,
            "document_type": doc_type,
            "is_tampered": item["is_tampered"],
            "tamper_type": item["tamper_type"],
            "latency_ms": latency_ms,
            "fields_evaluated": doc_fields,
            "fields_exact_match": doc_exact,
            "doc_accuracy_pct": round((doc_exact / max(doc_fields, 1)) * 100, 2),
            "doc_avg_cer": round(doc_cer_sum / max(doc_fields, 1), 4),
            "field_comparisons": doc_field_comparisons,
        })

        print(f"[{idx}/{len(manifest)}] {doc_id} ({doc_type}) -> {doc_exact}/{doc_fields} exact ({latency_ms}ms)")

    total_duration = time.perf_counter() - t_start_all

    # Aggregate summaries
    overall_accuracy = round((exact_matches / max(total_fields, 1)) * 100, 2)
    overall_cer = round(cer_sum / max(total_fields, 1), 4)

    per_doc_type_summary = {}
    for dt, s in doc_type_stats.items():
        tot = s["total_fields"]
        ex = s["exact_matches"]
        c_sum = s["cer_sum"]
        per_doc_type_summary[dt] = {
            "document_count": s["doc_count"],
            "total_fields": tot,
            "exact_matches": ex,
            "accuracy_pct": round((ex / max(tot, 1)) * 100, 2),
            "avg_cer": round(c_sum / max(tot, 1), 4),
        }

    # Sort worst 5 fields by CER descending
    worst_5_fields = sorted(field_error_log, key=lambda x: x["cer"], reverse=True)[:5]

    benchmark_data = {
        "benchmark_name": "SentinelAuth Module 1 OCR Extraction Benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disclaimer": "Benchmarked against synthetically generated documents and tampering, not real forged government documents (which cannot be legally sourced for testing).",
        "documents_evaluated": len(manifest),
        "total_fields_evaluated": total_fields,
        "total_exact_matches": exact_matches,
        "overall_accuracy_pct": overall_accuracy,
        "overall_avg_cer": overall_cer,
        "total_time_sec": round(total_duration, 2),
        "per_document_type": per_doc_type_summary,
        "worst_5_fields": worst_5_fields,
        "document_evaluations": doc_evaluations,
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    print("\n" + "=" * 78)
    print("OCR BENCHMARK SUMMARY RESULTS")
    print("=" * 78)
    print(f"Total Documents:        {len(manifest)}")
    print(f"Total Fields Checked:   {total_fields}")
    print(f"Overall Accuracy:       {overall_accuracy}%*")
    print(f"Overall Average CER:    {overall_cer}*")
    print("\nBreakdown by Document Type:")
    for dt, s in per_doc_type_summary.items():
        print(f"  - {dt:<22}: Accuracy {s['accuracy_pct']:>6.2f}%* | CER: {s['avg_cer']:>6.4f}* (docs: {s['document_count']})")

    print("\nTop 5 Worst-Performing Fields / Discrepancies:")
    for w in worst_5_fields:
        print(f"  - [{w['doc_id']}] {w['field_name']}: CER={w['cer']:.4f}* (GT: '{w['ground_truth']}' vs EXT: '{w['extracted']}')")

    print("\n* Benchmarked against synthetically generated documents and tampering, not real forged government documents (which cannot be legally sourced for testing).")
    print(f"\nSaved detailed JSON to: {OUTPUT_JSON}")
    return benchmark_data


if __name__ == "__main__":
    run_ocr_benchmark()
