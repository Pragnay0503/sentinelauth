"""
generate_calibration_dataset.py - Generates 250 clean documents (50 PAN, 50 Aadhaar, 50 Voter ID, 50 Passport, 50 Visa).
Seeds >= 10000 (different from test set), same physical_scan camera simulation.
Strictly used for calibration (percentile threshold determination), NEVER for testing.
"""
import io
import json
import os
import random
import sys
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.benchmarks.dataset_generator import (
    generate_pan_card,
    generate_aadhaar_card,
    generate_voter_card,
    generate_passport_card,
    generate_visa_card,
    generate_verhoeff,
    apply_camera_capture_simulation,
    verify_template_alignment,
)

CALIBRATION_DIR = os.path.join(BASE_DIR, "data", "calibration_dataset")
IMAGES_DIR = os.path.join(CALIBRATION_DIR, "images")
MANIFEST_PATH = os.path.join(CALIBRATION_DIR, "manifest.json")

FIRST_NAMES = [
    "AARAV", "VIVAAN", "ADITYA", "VIHAAN", "ARJUN", "SAI", "REYNAH", "AYAN", "KRISHNA", "ISHAN",
    "SHAURYA", "ATHARVA", "ANANYA", "DIYA", "SAANVI", "PARI", "AADHIL", "KAVYA", "AVANI", "MYRA",
    "SANYA", "AAROHI", "PRANAV", "HARSH", "KUNAL", "ROHAN", "MANISH", "SURESH", "RAMESH", "RAJESH",
    "POOJA", "PRIYA", "NEHA", "SNEHA", "SHWETA", "DIVYA", "ANITA", "SUNITA", "MEERA", "RITU",
    "AMIT", "SUMIT", "GAURAV", "SACHIN", "VIKRAM", "DEEPAK", "TARUN", "VARUN", "KAPIL", "SANJAY"
]

LAST_NAMES = [
    "SHARMA", "VERMA", "GUPTA", "PATEL", "MEHTA", "JAIN", "SINGH", "KUMAR", "REDDY", "NAIR",
    "IYER", "RAO", "JOSHI", "CHOPRA", "SEN", "TIWARI", "CHATTERJEE", "BANSAL", "DESHMUKH", "HEGDE",
    "BALAN", "SHAH", "RATHORE", "MISHRA", "AGRAWAL", "BHAT", "CHOUDHARY", "DAS", "DUTTA", "GOWDA",
    "KHAN", "MALHOTRA", "MENON", "MUKHERJEE", "PANDEY", "PILLAI", "PRASAD", "ROY", "SAXENA", "SETHI"
]

CITIES = [
    ("Connaught Place, New Delhi", "Delhi", "110001"),
    ("Bandra West, Mumbai", "Maharashtra", "400050"),
    ("Indiranagar, Bengaluru", "Karnataka", "560038"),
    ("Mylapore, Chennai", "Tamil Nadu", "600004"),
    ("Salt Lake, Kolkata", "West Bengal", "700064"),
    ("Banjara Hills, Hyderabad", "Telangana", "500034"),
    ("Navrangpura, Ahmedabad", "Gujarat", "380009"),
    ("Civil Lines, Jaipur", "Rajasthan", "302006"),
    ("Hazratganj, Lucknow", "Uttar Pradesh", "226001"),
    ("Shivajinagar, Pune", "Maharashtra", "411005"),
]

INTERNATIONAL_SURNAMES = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ",
    "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN",
    "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK", "RAMIREZ", "LEWIS", "ROBINSON",
    "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT", "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES",
    "GREEN", "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL", "CARTER", "ROBERTS"
]

INTERNATIONAL_GIVEN_NAMES = [
    "JAMES", "MARY", "ROBERT", "PATRICIA", "JOHN", "JENNIFER", "MICHAEL", "LINDA", "DAVID", "ELIZABETH",
    "WILLIAM", "BARBARA", "RICHARD", "SUSAN", "JOSEPH", "JESSICA", "THOMAS", "SARAH", "CHARLES", "KAREN",
    "CHRISTOPHER", "LISA", "DANIEL", "NANCY", "MATTHEW", "BETTY", "ANTHONY", "MARGARET", "MARK", "SANDRA",
    "DONALD", "ASHLEY", "STEVEN", "KIMBERLY", "PAUL", "EMILY", "ANDREW", "DONNA", "JOSHUA", "MICHELLE",
    "KENNETH", "CAROL", "KEVIN", "AMANDA", "BRIAN", "DOROTHY", "GEORGE", "MELISSA", "EDWARD", "DEBORAH"
]


import hashlib

CACHE_META_PATH = os.path.join(CALIBRATION_DIR, ".cache_meta.json")


def _compute_generator_fingerprint(count_per_type: int) -> str:
    h = hashlib.sha256()
    h.update(str(count_per_type).encode("utf-8"))
    gen_file = os.path.join(BASE_DIR, "backend", "benchmarks", "dataset_generator.py")
    if os.path.exists(gen_file):
        with open(gen_file, "rb") as f:
            h.update(f.read())
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def generate_calibration_dataset(count_per_type: int = 50) -> List[Dict[str, Any]]:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    fingerprint = _compute_generator_fingerprint(count_per_type)

    if os.path.exists(MANIFEST_PATH) and os.path.exists(CACHE_META_PATH):
        try:
            with open(CACHE_META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("fingerprint") == fingerprint:
                with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                    cached_manifest = json.load(f)
                expected_count = count_per_type * 5
                if len(cached_manifest) == expected_count and all(
                    os.path.exists(os.path.join(BASE_DIR, d["file_path"])) for d in cached_manifest
                ):
                    print(f"[Calibration] Cached calibration set ({len(cached_manifest)} docs) is up-to-date. Skipping regeneration.")
                    return cached_manifest
        except Exception:
            pass

    manifest: List[Dict[str, Any]] = []

    # 1. 50 CLEAN PAN CARDS
    print(f"[Calibration] Generating {count_per_type} PAN cards...")
    for idx in range(1, count_per_type + 1):
        seed = 10000 + idx
        fname = f"pan_calib_{idx:03d}.png"
        fpath = os.path.join(IMAGES_DIR, fname)

        fn = FIRST_NAMES[(idx * 3) % len(FIRST_NAMES)]
        ln = LAST_NAMES[(idx * 7) % len(LAST_NAMES)]
        father_fn = FIRST_NAMES[(idx * 2 + 1) % len(FIRST_NAMES)]
        pan = f"A{chr(65 + (idx % 26))}CPA{1000 + idx * 17:04d}{chr(65 + (idx * 3 % 26))}"
        dob = f"{(idx * 5 % 28) + 1:02d}/{(idx * 7 % 12) + 1:02d}/{1970 + (idx % 30)}"

        fields = {
            "pan_number": pan,
            "name": f"{fn} {ln}",
            "father_name": f"{father_fn} {ln}",
            "date_of_birth": dob,
        }

        base_clean = generate_pan_card(fields)
        verify_template_alignment(base_clean, "national_id_pan")
        clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
        clean_img.save(fpath)

        manifest.append({
            "id": f"pan_calib_{idx:03d}",
            "file_path": os.path.relpath(fpath, BASE_DIR).replace("\\", "/"),
            "document_type": "national_id_pan",
            "is_tampered": False,
            "tamper_type": None,
            "tamper_details": None,
            "tampered_field": None,
            "tampered_bbox": None,
            "ground_truth_fields": fields,
        })

    # 2. 50 CLEAN AADHAAR CARDS
    print(f"[Calibration] Generating {count_per_type} Aadhaar cards...")
    for idx in range(1, count_per_type + 1):
        seed = 20000 + idx
        fname = f"aadhaar_calib_{idx:03d}.png"
        fpath = os.path.join(IMAGES_DIR, fname)

        fn = FIRST_NAMES[(idx * 5) % len(FIRST_NAMES)]
        ln = LAST_NAMES[(idx * 11) % len(LAST_NAMES)]
        raw_uid = f"{20000000000 + idx * 7391823:011d}"
        valid_uid = generate_verhoeff(raw_uid)
        gender = "Female" if idx % 2 == 0 else "Male"
        dob = f"{(idx * 3 % 28) + 1:02d}/{(idx * 5 % 12) + 1:02d}/{1975 + (idx % 25)}"
        loc = CITIES[idx % len(CITIES)]
        address = f"House {idx * 7}, {loc[0]}, {loc[1]} {loc[2]}"

        fields = {
            "aadhaar_number": f"{valid_uid[0:4]} {valid_uid[4:8]} {valid_uid[8:12]}",
            "name": f"{fn} {ln}",
            "date_of_birth": dob,
            "gender": gender,
            "address": address,
        }

        base_clean = generate_aadhaar_card(fields)
        verify_template_alignment(base_clean, "national_id_aadhaar")
        clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
        clean_img.save(fpath)

        manifest.append({
            "id": f"aadhaar_calib_{idx:03d}",
            "file_path": os.path.relpath(fpath, BASE_DIR).replace("\\", "/"),
            "document_type": "national_id_aadhaar",
            "is_tampered": False,
            "tamper_type": None,
            "tamper_details": None,
            "tampered_field": None,
            "tampered_bbox": None,
            "ground_truth_fields": fields,
        })

    # 3. 50 CLEAN VOTER ID CARDS
    print(f"[Calibration] Generating {count_per_type} Voter ID cards...")
    for idx in range(1, count_per_type + 1):
        seed = 30000 + idx
        fname = f"voter_calib_{idx:03d}.png"
        fpath = os.path.join(IMAGES_DIR, fname)

        fn = FIRST_NAMES[(idx * 7) % len(FIRST_NAMES)]
        ln = LAST_NAMES[(idx * 13) % len(LAST_NAMES)]
        father_fn = FIRST_NAMES[(idx * 2 + 5) % len(FIRST_NAMES)]
        gender = "Female" if idx % 2 == 1 else "Male"
        prefix = ["WBD", "DEL", "MAH", "KAR", "TAM", "GUJ", "RAJ", "UPP"][idx % 8]
        epic = f"{prefix}{1000000 + idx * 8371:07d}"
        dob = f"{(idx * 7 % 28) + 1:02d}/{(idx * 3 % 12) + 1:02d}/{1968 + (idx % 32)}"
        loc = CITIES[(idx + 3) % len(CITIES)]
        address = f"Flat {idx * 4}, {loc[0]}, {loc[1]}"

        fields = {
            "epic_number": epic,
            "name": f"{fn} {ln}",
            "father_name": f"{father_fn} {ln}",
            "gender": gender,
            "date_of_birth": dob,
            "address": address,
        }

        base_clean = generate_voter_card(fields)
        verify_template_alignment(base_clean, "national_id_voter")
        clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
        clean_img.save(fpath)

        manifest.append({
            "id": f"voter_calib_{idx:03d}",
            "file_path": os.path.relpath(fpath, BASE_DIR).replace("\\", "/"),
            "document_type": "national_id_voter",
            "is_tampered": False,
            "tamper_type": None,
            "tamper_details": None,
            "tampered_field": None,
            "tampered_bbox": None,
            "ground_truth_fields": fields,
        })

    # 4. 50 CLEAN PASSPORT CARDS
    print(f"[Calibration] Generating {count_per_type} Passport cards...")
    for idx in range(1, count_per_type + 1):
        seed = 40000 + idx
        fname = f"passport_calib_{idx:03d}.png"
        fpath = os.path.join(IMAGES_DIR, fname)

        sur = INTERNATIONAL_SURNAMES[idx % len(INTERNATIONAL_SURNAMES)]
        given = INTERNATIONAL_GIVEN_NAMES[(idx * 3) % len(INTERNATIONAL_GIVEN_NAMES)]
        gender = "F" if idx % 2 == 0 else "M"
        p_num = f"U{10000000 + idx * 91823:08d}"
        dob = f"{(idx * 7 % 28) + 1:02d}/{(idx * 5 % 12) + 1:02d}/{1970 + (idx % 25)}"
        exp = f"{(idx * 7 % 28) + 1:02d}/{(idx * 5 % 12) + 1:02d}/{2030 + (idx % 5)}"

        fields = {
            "passport_number": p_num,
            "surname": sur,
            "given_names": given,
            "nationality": "UTO",
            "date_of_birth": dob,
            "sex": gender,
            "date_of_expiry": exp,
        }

        base_clean = generate_passport_card(fields)
        verify_template_alignment(base_clean, "passport")
        clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
        clean_img.save(fpath)

        manifest.append({
            "id": f"passport_calib_{idx:03d}",
            "file_path": os.path.relpath(fpath, BASE_DIR).replace("\\", "/"),
            "document_type": "passport",
            "is_tampered": False,
            "tamper_type": None,
            "tamper_details": None,
            "tampered_field": None,
            "tampered_bbox": None,
            "ground_truth_fields": fields,
        })

    # 5. 50 CLEAN VISA CARDS
    print(f"[Calibration] Generating {count_per_type} Visa cards...")
    for idx in range(1, count_per_type + 1):
        seed = 50000 + idx
        fname = f"visa_calib_{idx:03d}.png"
        fpath = os.path.join(IMAGES_DIR, fname)

        sur = INTERNATIONAL_SURNAMES[(idx * 7) % len(INTERNATIONAL_SURNAMES)]
        given = INTERNATIONAL_GIVEN_NAMES[(idx * 11) % len(INTERNATIONAL_GIVEN_NAMES)]
        gender = "F" if idx % 2 == 1 else "M"
        v_num = f"V{20000000 + idx * 81723:08d}"
        p_num = f"U{10000000 + idx * 91823:08d}"
        dob = f"{(idx * 3 % 28) + 1:02d}/{(idx * 7 % 12) + 1:02d}/{1972 + (idx % 26)}"
        vf = f"01/0{(idx % 9) + 1}/2023"
        exp = f"01/0{(idx % 9) + 1}/2025"

        fields = {
            "visa_number": v_num,
            "surname": sur,
            "given_names": given,
            "passport_number": p_num,
            "nationality": "UTO",
            "date_of_birth": dob,
            "sex": gender,
            "valid_from": vf,
            "date_of_expiry": exp,
        }

        base_clean = generate_visa_card(fields)
        verify_template_alignment(base_clean, "visa")
        clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
        clean_img.save(fpath)

        manifest.append({
            "id": f"visa_calib_{idx:03d}",
            "file_path": os.path.relpath(fpath, BASE_DIR).replace("\\", "/"),
            "document_type": "visa",
            "is_tampered": False,
            "tamper_type": None,
            "tamper_details": None,
            "tampered_field": None,
            "tampered_bbox": None,
            "ground_truth_fields": fields,
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(CACHE_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": fingerprint, "count": len(manifest), "count_per_type": count_per_type}, f, indent=2)

    print(f"[Calibration] Finished generating {len(manifest)} calibration documents at {IMAGES_DIR}")
    print(f"[Calibration] Manifest saved to {MANIFEST_PATH}")
    return manifest


if __name__ == "__main__":
    generate_calibration_dataset(count_per_type=50)
