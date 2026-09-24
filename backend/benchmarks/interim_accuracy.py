import json
import os
import sys
import hashlib

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from collections import defaultdict
from backend.modules.ocr_extraction.mrz_parser import detect_mrz_lines, _icao_checksum

base_dir = os.getcwd()
cache_dir = os.path.join(base_dir, 'data', 'cache', 'ocr')

m_test = json.load(open('data/synthetic_dataset/manifest.json'))
m_calib = json.load(open('data/calibration_dataset/manifest.json'))
all_clean = [x for x in (m_test + m_calib) if not x.get('is_tampered', False)]

cached_items = []
for item in all_clean:
    p = os.path.join(base_dir, item['file_path'])
    if not os.path.exists(p):
        continue
    with open(p, 'rb') as f:
        data = f.read()
    h = hashlib.sha256(data)
    h.update(str(item['document_type']).encode('utf-8'))
    cf = os.path.join(cache_dir, f'{h.hexdigest()}.json')
    if os.path.exists(cf):
        cached_items.append((item, json.load(open(cf))))

print(f'Cached clean items found: {len(cached_items)} / {len(all_clean)}')

# Check fields accuracy
stats = defaultdict(lambda: defaultdict(lambda: {'total': 0, 'correct': 0}))
mrz_stats = defaultdict(lambda: {'total': 0, 'l1': 0, 'l2': 0})

for item, ocr in cached_items:
    dt = item['document_type']
    gt = item['ground_truth_fields']
    ext = ocr.get('extracted_fields', {})
    raw_text = ocr.get('raw_ocr_text', '')

    for f_name, gt_val in gt.items():
        cand_keys = [f_name]
        if f_name == 'date_of_birth':
            cand_keys.extend(['dob', 'birth_date'])
        elif f_name == 'dob':
            cand_keys.extend(['date_of_birth'])
        elif f_name == 'pan_number':
            cand_keys.extend(['document_number', 'id_number'])
        elif f_name == 'aadhaar_number':
            cand_keys.extend(['document_number', 'id_number'])
        elif f_name == 'epic_number':
            cand_keys.extend(['document_number', 'id_number'])
        elif f_name == 'passport_number':
            cand_keys.extend(['document_number', 'id_number'])
        elif f_name == 'visa_number':
            cand_keys.extend(['document_number', 'id_number'])

        val = ''
        for ck in cand_keys:
            if ck in ext and ext[ck]['value'] != 'not applicable for this document type':
                val = ext[ck]['value'].strip()
                break

        norm_gt = str(gt_val).strip().upper()
        norm_ext = str(val).strip().upper()
        if f_name in ('aadhaar_number', 'pan_number', 'epic_number', 'passport_number', 'visa_number'):
            norm_gt = norm_gt.replace(' ', '')
            norm_ext = norm_ext.replace(' ', '')

        stats[dt][f_name]['total'] += 1
        if norm_ext == norm_gt:
            stats[dt][f_name]['correct'] += 1

    if dt in ('passport', 'visa'):
        surname = gt.get('surname', '')
        given = gt.get('given_names', '')
        name_clean = f"{surname}<<{given.replace(' ', '<')}"
        prefix = 'P<UTO' if dt == 'passport' else 'V<UTO'
        exp_l1 = (f'{prefix}{name_clean}' + '<' * 44)[:44]

        doc_k = 'passport_number' if dt == 'passport' else 'visa_number'
        doc_num = (gt.get(doc_k, '') + '<' * 9)[:9]
        c_doc = str(_icao_checksum(doc_num))
        d_parts = gt.get('date_of_birth', '01/01/1980').split('/')
        dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
        c_dob = str(_icao_checksum(dob_yymmdd))
        e_parts = gt.get('date_of_expiry', '01/01/2030').split('/')
        exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
        c_exp = str(_icao_checksum(exp_yymmdd))
        if dt == 'passport':
            opt = '<' * 14
            c_opt = '<'
            comp = str(_icao_checksum(doc_num + c_doc + dob_yymmdd + c_dob + exp_yymmdd + c_exp + opt + c_opt))
            exp_l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{gt.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"
        else:
            opt = '<' * 16
            exp_l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{gt.get('sex', 'M')}{exp_yymmdd}{c_exp}{opt}"

        cands = [l.strip().replace(' ', '').upper() for l in detect_mrz_lines(raw_text) if len(l.strip().replace(' ', '')) >= 36]
        mrz_stats[dt]['total'] += 1
        if any(c == exp_l1 for c in cands):
            mrz_stats[dt]['l1'] += 1
        if any(c == exp_l2 for c in cands):
            mrz_stats[dt]['l2'] += 1

print("\nPER-FIELD ACCURACY (PROCESSED CLEAN SAMPLES):")
for dt, f_dict in sorted(stats.items()):
    print(f'=== {dt} ===')
    for f, c in sorted(f_dict.items()):
        acc = c['correct'] / c['total'] * 100.0 if c['total'] > 0 else 0
        status = "PASS" if acc >= 95.0 else "FAIL (<95%)"
        print(f"  {f:<22}: {c['correct']:>3}/{c['total']:<3} ({acc:>5.1f}%) -> {status}")

print("\nMRZ LINE ACCURACY (EXACT 44 CHARACTERS):")
for dt, m in sorted(mrz_stats.items()):
    l1_acc = m['l1'] / m['total'] * 100.0 if m['total'] > 0 else 0
    l2_acc = m['l2'] / m['total'] * 100.0 if m['total'] > 0 else 0
    print(f"  {dt:<10}: Line 1 = {m['l1']}/{m['total']} ({l1_acc:.1f}%), Line 2 = {m['l2']}/{m['total']} ({l2_acc:.1f}%)")
