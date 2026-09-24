import json
import os
import sys
import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.modules.tampering_detection.field_forensics import analyze_all_document_fields

with open(os.path.join(BASE_DIR, 'data', 'synthetic_dataset', 'manifest.json')) as f:
    manifest = json.load(f)

with open(os.path.join(BASE_DIR, 'backend', 'modules', 'tampering_detection', 'calibrated_thresholds.json')) as f:
    calib = json.load(f)

clean_docs = [m for m in manifest if not m['is_tampered']]
tampered_docs = [m for m in manifest if m['is_tampered']]

print("Testing Calibrated Thresholds on 24 Clean Test Documents:")
clean_flagged = []
for c in clean_docs:
    img = cv2.imread(os.path.join(BASE_DIR, c['file_path']))
    res = analyze_all_document_fields(img, document_type=c['document_type'])
    flagged_fields = []
    for f, r in res.items():
        t_ela = calib.get(c['document_type'], {}).get(f, {}).get("ela_threshold_p99", 0.65)
        t_font = calib.get(c['document_type'], {}).get(f, {}).get("font_threshold_p01", 0.50)
        
        # Candidate rule:
        # Both anomalous, OR severe ELA anomaly, OR severe font anomaly
        is_tampered = (
            (r.ela_anomaly_score > t_ela and r.font_consistency_score < t_font)
            or (r.ela_anomaly_score > min(1.0, t_ela + 0.08))
            or (r.font_consistency_score < max(0.1, t_font - 0.15))
        )
        if is_tampered:
            flagged_fields.append((f, r.ela_anomaly_score, t_ela, r.font_consistency_score, t_font))
    if flagged_fields:
        clean_flagged.append((c['id'], flagged_fields))
        print(f"  CLEAN FP: {c['id']} -> {flagged_fields}")

print(f"Total clean docs falsely flagged by field forensics: {len(clean_flagged)} / {len(clean_docs)}")

print("\nTesting on 24 Tampered Test Documents:")
for t in tampered_docs:
    img = cv2.imread(os.path.join(BASE_DIR, t['file_path']))
    res = analyze_all_document_fields(img, document_type=t['document_type'])
    tf = t.get('tampered_field')
    flagged_fields = []
    for f, r in res.items():
        t_ela = calib.get(t['document_type'], {}).get(f, {}).get("ela_threshold_p99", 0.65)
        t_font = calib.get(t['document_type'], {}).get(f, {}).get("font_threshold_p01", 0.50)
        is_tampered = (
            (r.ela_anomaly_score > t_ela and r.font_consistency_score < t_font)
            or (r.ela_anomaly_score > min(1.0, t_ela + 0.08))
            or (r.font_consistency_score < max(0.1, t_font - 0.15))
        )
        if is_tampered:
            flagged_fields.append(f)
    print(f"  {t['id']} (tamper={t['tamper_type']}, field={tf}) -> Flagged fields: {flagged_fields}")
