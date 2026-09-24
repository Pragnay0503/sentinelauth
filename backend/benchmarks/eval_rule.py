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

def evaluate_rule():
    clean_fps = 0
    for c in clean_docs:
        img = cv2.imread(os.path.join(BASE_DIR, c['file_path']))
        res = analyze_all_document_fields(img, document_type=c['document_type'])
        flagged = False
        for f, r in res.items():
            t_ela = calib.get(c['document_type'], {}).get(f, {}).get("ela_threshold_p99", 0.65)
            t_font = calib.get(c['document_type'], {}).get(f, {}).get("font_threshold_p01", 0.50)
            
            # Calibrated rule
            is_tampered = (
                (r.ela_anomaly_score >= t_ela and r.font_consistency_score <= t_font)
                or (r.ela_anomaly_score >= min(1.0, max(0.70, t_ela + 0.07)))
                or (r.font_consistency_score <= max(0.20, t_font - 0.20) and r.ela_anomaly_score >= (t_ela * 0.70))
            )
            if is_tampered:
                flagged = True
                print(f"Clean FP: {c['id']} {f} (ELA={r.ela_anomaly_score} vs {t_ela}, Font={r.font_consistency_score} vs {t_font})")
        if flagged:
            clean_fps += 1
    print(f"Clean FPs: {clean_fps} / {len(clean_docs)}")

    tampered_detections = 0
    for t in tampered_docs:
        img = cv2.imread(os.path.join(BASE_DIR, t['file_path']))
        res = analyze_all_document_fields(img, document_type=t['document_type'])
        flagged_fields = []
        for f, r in res.items():
            t_ela = calib.get(t['document_type'], {}).get(f, {}).get("ela_threshold_p99", 0.65)
            t_font = calib.get(t['document_type'], {}).get(f, {}).get("font_threshold_p01", 0.50)
            is_tampered = (
                (r.ela_anomaly_score >= t_ela and r.font_consistency_score <= t_font)
                or (r.ela_anomaly_score >= min(1.0, max(0.70, t_ela + 0.07)))
                or (r.font_consistency_score <= max(0.20, t_font - 0.20) and r.ela_anomaly_score >= (t_ela * 0.70))
            )
            if is_tampered:
                flagged_fields.append(f)
        tf = t.get('tampered_field')
        if tf in flagged_fields:
            tampered_detections += 1
            print(f"TP Match: {t['id']} -> {flagged_fields} (GT: {tf})")
        elif flagged_fields:
            print(f"Wrong reason / other field: {t['id']} -> {flagged_fields} (GT: {tf})")
        else:
            print(f"Missed: {t['id']} (GT: {tf})")
    print(f"Field forensics direct TPs: {tampered_detections} / {len(tampered_docs)}")

evaluate_rule()
