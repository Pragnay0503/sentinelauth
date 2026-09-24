import json
import os
import sys
import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.tampering_detection.field_forensics import analyze_all_document_fields

with open(os.path.join(BASE_DIR, 'data', 'synthetic_dataset', 'manifest.json')) as f:
    m = json.load(f)

with open(os.path.join(BASE_DIR, 'backend', 'modules', 'tampering_detection', 'calibrated_thresholds.json')) as f:
    calib = json.load(f)

tampered_edits = [x for x in m if x['tamper_type'] in ('text_edit', 'stamp_duplicate')]
print("=" * 80)
print(f"{'Doc ID':<35} | {'Field':<10} | {'ELA':<6} | {'P99':<6} | {'Font':<6} | {'P01':<6}")
print("=" * 80)

for item in tampered_edits:
    img = cv2.imread(os.path.join(BASE_DIR, item['file_path']))
    doc_type = item['document_type']
    res = analyze_all_document_fields(img, document_type=doc_type)
    tf = item['tampered_field']
    r = res.get(tf)
    if r:
        p99 = calib.get(doc_type, {}).get(tf, {}).get("ela_threshold_p99", 0.65)
        p01 = calib.get(doc_type, {}).get(tf, {}).get("font_threshold_p01", 0.50)
        print(f"{item['id']:<35} | {tf:<10} | {r.ela_anomaly_score:<6.2f} | {p99:<6.2f} | {r.font_consistency_score:<6.2f} | {p01:<6.2f}")
