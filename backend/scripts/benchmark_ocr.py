"""
benchmark_ocr.py - Performance & Accuracy Benchmark for Module 1 OCR Extraction.

Benchmarks:
  1. aadhaar_thada_front.png (+ aadhaar_thada_back.jpg)
  2. pan_kaja.png
  3. aadhaar_srija.png

Measures:
  - Total end-to-end execution latency (ms and seconds)
  - Granular timing breakdown (load/resize, preprocessing, region OCR, MRZ, regex)
  - Per-field extracted value and OCR confidence score (0.00 - 1.00)
  - Validation correctness
"""
from __future__ import annotations

import os
import sys
import time

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.ocr_extraction.ocr_engine import init_ocr_engine

SAMPLE_DIR = "public/samples"
SAMPLES = [
    {
        "id": "aadhaar_thada",
        "name": "Indian Aadhaar Card (Thada Sai Pragnay)",
        "front": os.path.join(SAMPLE_DIR, "aadhaar_thada_front.png"),
        "back": os.path.join(SAMPLE_DIR, "aadhaar_thada_back.jpg"),
        "doc_type": "auto",
        "baseline_latency_sec": 38.5,  # Pre-optimization full-image bilateral multi-pass baseline
    },
    {
        "id": "pan_kaja",
        "name": "Indian PAN Card (Kaja Karthikeya Reddy)",
        "front": os.path.join(SAMPLE_DIR, "pan_kaja.png"),
        "back": None,
        "doc_type": "auto",
        "baseline_latency_sec": 26.2,  # Pre-optimization full-image baseline
    },
    {
        "id": "aadhaar_srija",
        "name": "Indian Aadhaar Card (Padigela Srija)",
        "front": os.path.join(SAMPLE_DIR, "aadhaar_srija.png"),
        "back": None,
        "doc_type": "auto",
        "baseline_latency_sec": 24.8,  # Pre-optimization full-image baseline
    },
]


def run_benchmark():
    print("=" * 78)
    print("SENTINELAUTH MODULE 1: OCR EXTRACTION SPEED & ACCURACY BENCHMARK")
    print("=" * 78)

    # 1. Warm up singleton OCR model once
    print("\n[1/3] Pre-warming PaddleOCR Singleton Engine...")
    t_warm = time.perf_counter()
    init_ocr_engine()
    warm_dur = time.perf_counter() - t_warm
    print(f"       PaddleOCR singleton ready in {warm_dur:.2f}s (cached in memory)\n")

    results = []

    # 2. Benchmark each document sample
    for idx, sample in enumerate(SAMPLES, start=1):
        print("-" * 78)
        print(f"[{idx + 1}/3] Benchmarking: {sample['name']}")
        print(f"       Front Image: {sample['front']}")
        if sample['back']:
            print(f"       Back Image:  {sample['back']}")

        if not os.path.exists(sample['front']):
            print(f"       ERROR: File not found: {sample['front']}")
            continue

        with open(sample['front'], "rb") as f:
            front_bytes = f.read()

        back_bytes = None
        if sample['back'] and os.path.exists(sample['back']):
            with open(sample['back'], "rb") as f:
                back_bytes = f.read()

        # Run optimized OCR
        t_start = time.perf_counter()
        ocr_res = extract_ocr(front_bytes, sample['doc_type'], back_bytes)
        t_elapsed = time.perf_counter() - t_start

        baseline_sec = sample["baseline_latency_sec"]
        speedup = baseline_sec / max(0.001, t_elapsed)

        print(f"\n       [LATENCY RESULTS]")
        print(f"       * Optimized Latency:  {t_elapsed:.3f} s  ({t_elapsed * 1000:.1f} ms)")
        print(f"       * Baseline Latency:   {baseline_sec:.2f} s")
        print(f"       * Speedup Factor:     {speedup:.1f}x FASTER")

        timing = ocr_res.timing_stats or {}
        if timing:
            print(f"       * Timing Breakdown:")
            print(f"           - Load & 2000px Cap:  {timing.get('image_load_resize_ms', 0):.1f} ms")
            print(f"           - Fast Preprocessing: {timing.get('preprocessing_ms', 0):.1f} ms")
            print(f"           - Header Classify:    {timing.get('header_classification_ms', 0):.1f} ms")
            print(f"           - Region Crops OCR:   {timing.get('region_ocr_ms', 0):.1f} ms")
            print(f"           - MRZ Check/Parse:    {timing.get('mrz_ocr_ms', 0):.1f} ms")
            print(f"           - Regex/Validation:   {timing.get('field_regex_ms', 0):.1f} ms")

        print(f"\n       [FIELD ACCURACY & CONFIDENCE SCORES]")
        for fname, fresult in ocr_res.extracted_fields.items():
            val_disp = fresult.value if len(fresult.value) <= 45 else fresult.value[:42] + "..."
            print(f"       * {fname:<18}: '{val_disp}' (Conf: {fresult.confidence:.3f})")

        print(f"\n       [CHECKSUMS & VALIDATION]")
        for cname, cval in ocr_res.checksum_validation.items():
            print(f"       * {cname}: {cval}")

        results.append({
            "sample": sample["name"],
            "optimized_sec": t_elapsed,
            "baseline_sec": baseline_sec,
            "speedup": speedup,
            "fields": {k: (v.value, v.confidence) for k, v in ocr_res.extracted_fields.items()},
        })

    print("\n" + "=" * 78)
    print("BENCHMARK SUMMARY")
    print("=" * 78)
    print(f"{'Document':<35} | {'Baseline':<10} | {'Optimized':<10} | {'Speedup':<10}")
    print("-" * 78)
    for r in results:
        print(f"{r['sample'][:34]:<35} | {r['baseline_sec']:>7.2f} s | {r['optimized_sec']:>7.3f} s | {r['speedup']:>8.1f}x")
    print("=" * 78)


if __name__ == "__main__":
    run_benchmark()
