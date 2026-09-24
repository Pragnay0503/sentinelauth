"""
profile_pipeline.py - Stage-by-stage profiler for SentinelAuth benchmark pipeline.
Times: Generation, Camera Simulation, OCR, ELA, Face Model Detection, Field Forensics.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.benchmarks.dataset_generator import (
    generate_pan_card,
    generate_aadhaar_card,
    generate_voter_card,
    apply_camera_capture_simulation,
)
from backend.modules.ocr_extraction.extractor import extract_ocr
from backend.modules.tampering_detection.ela import compute_ela
from backend.modules.face_verification.engine import get_face_engine
from backend.modules.tampering_detection.field_forensics import analyze_all_document_fields

MANIFEST_PATH = os.path.join(BASE_DIR, "data", "synthetic_dataset", "manifest.json")

def run_profiler(num_docs: int = 12):
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Filter to Indian IDs (the 48-doc benchmark)
    manifest_48 = [d for d in manifest if d["document_type"] in ("national_id_pan", "national_id_aadhaar", "national_id_voter")][:num_docs]
    n = len(manifest_48)
    print(f"Profiling pipeline across {n} sample documents (extrapolating to 48 docs)...")

    stage_times: Dict[str, List[float]] = {
        "generation": [],
        "camera_simulation": [],
        "ocr": [],
        "ela": [],
        "face_detection": [],
        "field_forensics": [],
    }

    for idx, item in enumerate(manifest_48, 1):
        dt = item["document_type"]
        gt = item["ground_truth_fields"]
        fpath = os.path.join(BASE_DIR, item["file_path"])

        # 1. Generation
        t0 = time.perf_counter()
        if dt == "national_id_pan":
            base = generate_pan_card(gt)
        elif dt == "national_id_aadhaar":
            base = generate_aadhaar_card(gt)
        else:
            base = generate_voter_card(gt)
        stage_times["generation"].append(time.perf_counter() - t0)

        # 2. Camera Simulation
        t0 = time.perf_counter()
        sim_img = apply_camera_capture_simulation(base, seed=12345 + idx)
        stage_times["camera_simulation"].append(time.perf_counter() - t0)

        # Load image for downstream analysis
        with open(fpath, "rb") as f:
            img_bytes = f.read()
        cv_img = cv2.imread(fpath)

        # 3. OCR
        t0 = time.perf_counter()
        ocr_res = extract_ocr(img_bytes, document_type=dt)
        stage_times["ocr"].append(time.perf_counter() - t0)

        # 4. ELA
        t0 = time.perf_counter()
        ela_res, _ = compute_ela(img_bytes)
        stage_times["ela"].append(time.perf_counter() - t0)

        # 5. Face Detection / Model
        t0 = time.perf_counter()
        fe = get_face_engine()
        fe._detect_best_face(cv_img)
        stage_times["face_detection"].append(time.perf_counter() - t0)

        # 6. Field Forensics
        t0 = time.perf_counter()
        ff_res = analyze_all_document_fields(cv_img, document_type=dt)
        stage_times["field_forensics"].append(time.perf_counter() - t0)

        print(f"  Doc {idx:02d}/{n:02d} ({dt}): OCR={stage_times['ocr'][-1]:.2f}s, FF={stage_times['field_forensics'][-1]:.2f}s, Face={stage_times['face_detection'][-1]:.2f}s, Sim={stage_times['camera_simulation'][-1]:.2f}s")

    print("\n" + "=" * 80)
    print("PIPELINE PROFILING RESULTS (MEASURED PER-DOC & EXTRAPOLATED TO 48 DOCS)")
    print("=" * 80)
    print(f"{'Stage Name':<25} | {'Avg Sec/Doc':<15} | {'Min (s)':<10} | {'Max (s)':<10} | {'Total 48 Docs':<15}")
    print("-" * 80)

    summary = []
    for stage, times in stage_times.items():
        avg_t = np.mean(times)
        min_t = np.min(times)
        max_t = np.max(times)
        tot_48 = avg_t * 48
        summary.append((stage, avg_t, min_t, max_t, tot_48))

    summary.sort(key=lambda x: x[1], reverse=True)
    for stage, avg_t, min_t, max_t, tot_48 in summary:
        print(f"{stage:<25} | {avg_t:>10.3f} s  | {min_t:>7.3f} s | {max_t:>7.3f} s | {tot_48:>10.1f} s")

    print("=" * 80)
    print("\nTOP 3 TIME SINKS:")
    for rank, (stage, avg_t, min_t, max_t, tot_48) in enumerate(summary[:3], 1):
        print(f"  {rank}. {stage.upper()}: {avg_t:.3f}s per doc ({tot_48:.1f}s total for 48 docs)")

if __name__ == "__main__":
    run_profiler(num_docs=12)
