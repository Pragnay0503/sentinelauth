"""
run_all.py - Master Orchestrator for SentinelAuth Benchmarking Suite.

1. Ensures synthetic dataset and manifest are present (generates if missing).
2. Executes Module 1 OCR Extraction Benchmark (accuracy, CER, worst-5 fields).
3. Executes Module 3 Forensic Tampering Benchmark (precision, recall, F1, confusion matrix, threshold sweep).
4. Generates a comprehensive benchmark_report.md with mandatory synthetic disclaimer adjacent to every metric.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.benchmarks.dataset_generator import generate_dataset, MANIFEST_PATH
from backend.benchmarks.ocr_benchmark import run_ocr_benchmark
from backend.benchmarks.tampering_benchmark import run_tampering_benchmark

REPORT_PATH = os.path.join(BASE_DIR, "benchmark_report.md")
REPORT_PATH_PKG = os.path.join(BASE_DIR, "backend", "benchmarks", "benchmark_report.md")

DISCLAIMER_NOTE = (
    "*Benchmarked against synthetically generated documents and tampering, "
    "not real forged government documents (which cannot be legally sourced for testing).*"
)


def generate_markdown_report(ocr_res: Dict[str, Any], tamp_res: Dict[str, Any]) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    def_m = tamp_res["default_metrics"]
    opt_m = tamp_res["optimal_threshold"]
    clean_s = tamp_res["clean_summary"]

    md = f"""# SentinelAuth Forensic & OCR Benchmarking Report

> [!NOTE]
> **Evaluation Disclaimer**: All metrics in this report are benchmarked against synthetically generated documents and simulated tampering operations, not real forged government documents (which cannot be legally sourced for testing).

**Report Timestamp**: {timestamp}  
**Dataset Size**: {tamp_res['documents_evaluated']} documents ({tamp_res['clean_count']} genuine clean, {tamp_res['tampered_count']} tampered)  
**Document Types**: Indian PAN Card, Indian Aadhaar Card (with Verhoeff checksum & QR), Indian Voter ID Card (EPIC)

---

## 1. Executive Performance Summary

| Evaluation Suite | Core Metric | Measured Score | Legal / Synthetic Data Disclaimer |
| :--- | :--- | :--- | :--- |
| **Module 1: OCR Extraction** | Field Exact-Match Accuracy | **{ocr_res['overall_accuracy_pct']}%** | {DISCLAIMER_NOTE} |
| **Module 1: OCR Extraction** | Mean Character Error Rate (CER) | **{ocr_res['overall_avg_cer']:.4f}** | {DISCLAIMER_NOTE} |
| **Module 3: Tampering Detection** | Default Precision (threshold {def_m['threshold']}%) | **{def_m['precision_pct']}%** | {DISCLAIMER_NOTE} |
| **Module 3: Tampering Detection** | Default Recall (threshold {def_m['threshold']}%) | **{def_m['recall_pct']}%** | {DISCLAIMER_NOTE} |
| **Module 3: Tampering Detection** | Default F1 Score (threshold {def_m['threshold']}%) | **{def_m['f1_pct']}%** | {DISCLAIMER_NOTE} |
| **Module 3: Tampering Detection** | Clean False Positive Rate | **{clean_s['false_positive_rate_pct']}%** | {DISCLAIMER_NOTE} |
| **Module 3: Threshold Tuning** | Optimal Threshold | **{opt_m['threshold']}%** (F1: **{opt_m['f1_pct']}%**) | {DISCLAIMER_NOTE} |

---

## 2. Module 1: OCR Extraction In-Depth Evaluation

### Accuracy Breakdown by Document Type
| Document Type | Evaluated Documents | Total Fields | Exact Matches | Field Accuracy (%) | Mean CER | Benchmark Basis |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
"""

    for dt, s in ocr_res["per_document_type"].items():
        doc_display = dt.replace("national_id_", "").upper()
        md += f"| **{doc_display}** | {s['document_count']} | {s['total_fields']} | {s['exact_matches']} | **{s['accuracy_pct']}%** | **{s['avg_cer']:.4f}** | {DISCLAIMER_NOTE} |\n"

    md += f"""
### Worst-Performing Fields & OCR Discrepancies
The following 5 fields exhibited the highest Character Error Rate across the test corpus:

| Image ID | Document Type | Field Name | Ground Truth Value | Extracted OCR Value | Field CER | Benchmark Basis |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
"""
    for w in ocr_res["worst_5_fields"]:
        ext_display = w["extracted"] if w["extracted"] else "*(empty / missed)*"
        md += f"| `{w['doc_id']}` | {w['doc_type']} | `{w['field_name']}` | `{w['ground_truth']}` | `{ext_display}` | **{w['cer']:.4f}** | {DISCLAIMER_NOTE} |\n"

    md += f"""
---

## 3. Module 3: Forensic Tampering Detection In-Depth Evaluation

### Confusion Matrix at Default Threshold ({def_m['threshold']}%)
- **True Positives (TP)**: **{def_m['tp']}** *(tampered correctly flagged)* — {DISCLAIMER_NOTE}
- **False Positives (FP)**: **{def_m['fp']}** *(genuine incorrectly flagged)* — {DISCLAIMER_NOTE}
- **True Negatives (TN)**: **{def_m['tn']}** *(genuine correctly cleared)* — {DISCLAIMER_NOTE}
- **False Negatives (FN)**: **{def_m['fn']}** *(tampered missed)* — {DISCLAIMER_NOTE}

### Tampering Type Detection Breakdown
| Tamper Operation | Evaluated Samples | Detected (TP) | Detection Rate (%) | Average Tamper Score | Benchmark Basis |
| :--- | :---: | :---: | :---: | :---: | :--- |
"""
    for tt, b in tamp_res["tamper_type_breakdown"].items():
        display_name = tt.replace("_", " ").title()
        md += f"| **{display_name}** | {b['total_samples']} | {b['detected_count']} | **{b['detection_rate_pct']}%** | **{b['average_score_pct']}%** | {DISCLAIMER_NOTE} |\n"

    md += f"""
### Precision-Recall Tradeoff Across Threshold Sweep (0 - 100)
| Threshold | Precision (%) | Recall (%) | F1 Score (%) | True Pos (TP) | False Pos (FP) | True Neg (TN) | False Neg (FN) | Benchmark Basis |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
"""
    for s in tamp_res["threshold_sweep"]:
        is_opt = " *(Optimal)*" if s["threshold"] == opt_m["threshold"] else ""
        md += f"| **{s['threshold']:.0f}%**{is_opt} | {s['precision_pct']}% | {s['recall_pct']}% | **{s['f1_pct']}%** | {s['tp']} | {s['fp']} | {s['tn']} | {s['fn']} | {DISCLAIMER_NOTE} |\n"

    md += f"""
### Operational Threshold Recommendation
- **Current Default Threshold**: **{def_m['threshold']}%** delivers **{def_m['precision_pct']}% precision** and **{def_m['recall_pct']}% recall** (F1: **{def_m['f1_pct']}%**) — {DISCLAIMER_NOTE}
- **Optimal Empirical Threshold**: **{opt_m['threshold']}%** achieves maximum F1 score of **{opt_m['f1_pct']}%** with **{opt_m['precision_pct']}% precision** and **{opt_m['recall_pct']}% recall**, maintaining a false positive rate of **{opt_m['fpr_pct']}%** — {DISCLAIMER_NOTE}

---
*Report automatically compiled by SentinelAuth Benchmarking Suite.*
"""
    return md


def run_all():
    print("=" * 78)
    print("STARTING FULL SENTINELAUTH BENCHMARKING SUITE")
    print("=" * 78)

    # 1. Ensure dataset exists
    if not os.path.exists(MANIFEST_PATH):
        print("\n[Step 1/3] Manifest not found. Generating synthetic dataset...")
        generate_dataset(force=True)
    else:
        print(f"\n[Step 1/3] Using existing synthetic dataset manifest: {MANIFEST_PATH}")

    # 2. Run OCR benchmark
    print("\n[Step 2/3] Running Module 1 OCR Benchmark...")
    ocr_results = run_ocr_benchmark(MANIFEST_PATH)

    # 3. Run Tampering benchmark
    print("\n[Step 3/3] Running Module 3 Tampering Detection Benchmark...")
    tampering_results = run_tampering_benchmark(MANIFEST_PATH)

    # 4. Generate combined markdown report
    print("\nGenerating consolidated benchmark report...")
    report_md = generate_markdown_report(ocr_results, tampering_results)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(REPORT_PATH_PKG, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"\nConsolidated report written to:\n  - {REPORT_PATH}\n  - {REPORT_PATH_PKG}")
    print("\n" + "=" * 78)
    print("BENCHMARK RUN COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    run_all()
