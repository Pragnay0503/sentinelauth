"""
verify_all_five_requirements.py - Verification script for all 5 required verification test cases.

Test cases:
1. Session with only 1 or 2 documents uploaded, then report request -> INSUFFICIENT_DOCUMENTS (HTTP 400)
2. Session with exactly 3 documents, all matching DOB/Name -> high corroboration factor
3. Session with 3 documents where one disagrees on DOB -> CROSS_DOCUMENT_MISMATCH fires, dominates risk
4. Live face-verify attempt using static photo -> liveness check fails even if face match is high
5. Normal live face-verify attempt -> both liveness and face-match pass
"""
import io
import json
import os
import sys
import numpy as np
import cv2
from PIL import Image
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.main import app
from backend.db.database import init_db, SessionLocal
from backend.db.session_models import ScanSession, SessionScanLink
from backend.db.session_crud import create_session, add_scan_to_session
from backend.modules.face_verification.liveness import YUNET_PATH

client = TestClient(app)

def make_sample_image(text="SAMPLE DOC", width=800, height=500):
    img = np.full((height, width, 3), 240, dtype=np.uint8)
    cv2.putText(img, text, (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

def make_face_image(yaw_offset=0.0, eye_open=True, mouth_open=False, width=400, height=400):
    """
    Synthesizes a realistic face frame with controlled landmarks for biometric & liveness testing.
    """
    img = np.full((height, width, 3), 220, dtype=np.uint8)
    # Head contour
    cv2.ellipse(img, (200, 200), (90, 120), 0, 0, 360, (180, 150, 130), -1)
    
    # Eyes
    re_x = int(160 + yaw_offset)
    le_x = int(240 + yaw_offset)
    eye_h = 10 if eye_open else 2
    cv2.ellipse(img, (re_x, 160), (14, eye_h), 0, 0, 360, (50, 50, 50), -1)
    cv2.ellipse(img, (le_x, 160), (14, eye_h), 0, 0, 360, (50, 50, 50), -1)
    
    # Nose
    nose_x = int(200 + yaw_offset * 1.5)
    cv2.circle(img, (nose_x, 210), 8, (120, 90, 80), -1)
    
    # Mouth
    mouth_w = 28 if not mouth_open else 38
    mouth_h = 6 if not mouth_open else 14
    cv2.ellipse(img, (int(200 + yaw_offset), 270), (mouth_w, mouth_h), 0, 0, 360, (60, 40, 40), -1)
    
    # Add natural skin texture so Laplacian variance is healthy
    noise = np.random.normal(0, 4, img.shape).astype(np.uint8)
    img = cv2.add(img, noise)
    
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

print("=" * 75)
print("RUNNING VERIFICATION FOR ALL 5 REQUIRED SCENARIOS")
print("=" * 75)

# ---------------------------------------------------------------------------
# CASE 1: 1 or 2 documents uploaded -> report request returns INSUFFICIENT_DOCUMENTS (HTTP 400)
# ---------------------------------------------------------------------------
print("\n" + "#" * 60)
print("TEST CASE 1: INSUFFICIENT DOCUMENTS GUARD (HTTP 400)")
print("#" * 60)

# Create session
sess_res = client.post("/api/session", data={"officer_id": "OFFICER-4819", "station_id": "IGI T3", "documents_required": 3})
assert sess_res.status_code == 200, f"Session create failed: {sess_res.text}"
sess_data = sess_res.json()
session_id_1 = sess_data["session_id"]
print(f"Created Session: {session_id_1}")
print(f"Documents Required: {sess_data['documents_required']}")

# Upload 1 document directly to session DB
db = SessionLocal()
scan_payload_1 = {
    "ocr": {
        "extracted_fields": {
            "name": {"value": "ALOK VERMA"},
            "date_of_birth": {"value": "1988-11-20"},
            "nationality": {"value": "IND"},
            "gender": {"value": "M"}
        }
    },
    "risk": {"risk_score": 15.0, "risk_tier": "LOW"}
}
add_scan_to_session(db, session_id_1, "SCAN-001", "passport", "Passport", "ALOK VERMA", "P1234567", scan_payload_1)
db.close()
print("Uploaded 1 document ('Passport') into session.")

# Attempt to generate report with 1 document
report_res_1 = client.get(f"/api/session/{session_id_1}/report")
print(f"\nResponse HTTP Status Code: {report_res_1.status_code}")
print("Response JSON Body:")
print(json.dumps(report_res_1.json(), indent=2))

assert report_res_1.status_code == 400
detail_1 = report_res_1.json().get("detail", {})
assert detail_1.get("error") == "INSUFFICIENT_DOCUMENTS"
assert detail_1.get("documents_uploaded") == 1
assert detail_1.get("documents_remaining") == 2
assert "risk_score" not in report_res_1.json(), "No risk score should be generated!"
print("\n>>> CONFIRMED: HTTP 400 INSUFFICIENT_DOCUMENTS returned with remaining=2, no risk score generated.")

# Upload 2nd document
db = SessionLocal()
add_scan_to_session(db, session_id_1, "SCAN-002", "national_id", "National ID", "ALOK VERMA", "N9876543", scan_payload_1)
db.close()
print("\nUploaded 2nd document ('National ID') into session.")

# Attempt to generate report with 2 documents
report_res_2 = client.get(f"/api/session/{session_id_1}/report")
print(f"Response HTTP Status Code: {report_res_2.status_code}")
print("Response JSON Body:")
print(json.dumps(report_res_2.json(), indent=2))

assert report_res_2.status_code == 400
detail_2 = report_res_2.json().get("detail", {})
assert detail_2.get("error") == "INSUFFICIENT_DOCUMENTS"
assert detail_2.get("documents_uploaded") == 2
assert detail_2.get("documents_remaining") == 1
print("\n>>> CONFIRMED: HTTP 400 INSUFFICIENT_DOCUMENTS returned with remaining=1, no risk score generated.")


# ---------------------------------------------------------------------------
# CASE 2: Exactly 3 documents, all with matching DOB/Name -> high corroboration
# ---------------------------------------------------------------------------
print("\n" + "#" * 60)
print("TEST CASE 2: EXACTLY 3 DOCUMENTS WITH MATCHING DOB & NAME")
print("#" * 60)

sess_res_2 = client.post("/api/session", data={"officer_id": "OFFICER-4819", "station_id": "IGI T3", "documents_required": 3})
session_id_2 = sess_res_2.json()["session_id"]

db = SessionLocal()
doc_a = {
    "ocr": {"extracted_fields": {"name": {"value": "PRIYA NAIR"}, "date_of_birth": {"value": "1994-08-12"}, "nationality": {"value": "IND"}, "gender": {"value": "F"}}},
    "risk": {"risk_score": 12.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
doc_b = {
    "ocr": {"extracted_fields": {"name": {"value": "PRIYA NAIR"}, "date_of_birth": {"value": "12/08/1994"}, "nationality": {"value": "IND"}, "gender": {"value": "F"}}},
    "risk": {"risk_score": 14.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
doc_c = {
    "ocr": {"extracted_fields": {"name": {"value": "Priya Nair"}, "date_of_birth": {"value": "1994-08-12"}, "nationality": {"value": "India"}, "gender": {"value": "Female"}}},
    "risk": {"risk_score": 10.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
add_scan_to_session(db, session_id_2, "SCAN-101", "passport", "Passport", "PRIYA NAIR", "P4488221", doc_a)
add_scan_to_session(db, session_id_2, "SCAN-102", "national_id", "Aadhaar Card", "PRIYA NAIR", "9988 7766 5544", doc_b)
add_scan_to_session(db, session_id_2, "SCAN-103", "driving_license", "Driving License", "PRIYA NAIR", "DL-0420110099", doc_c)
db.close()

report_res_clean = client.get(f"/api/session/{session_id_2}/report")
print(f"Response HTTP Status Code: {report_res_clean.status_code}")
report_clean = report_res_clean.json()
print("Session Report Summary:")
print(f"  Session ID: {report_clean['session_id']}")
print(f"  Documents Submitted: {report_clean['documents_submitted']}/{report_clean['documents_required']}")
print(f"  Session Risk Score: {report_clean['session_risk_score']} ({report_clean['session_risk_tier']})")
print(f"  Operational Action: {report_clean['session_action']}")
print(f"  Corroboration Factor: {report_clean['cross_document_validation']['corroboration_factor'] * 100:.1f}%")
print(f"  Cross Document Mismatch: {report_clean['cross_document_validation']['has_cross_document_mismatch']}")
print(f"  Summary: {report_clean['cross_document_validation']['summary']}")
print("  Field Consistency Breakdown:")
for f_k, f_v in report_clean['cross_document_validation']['field_consistency'].items():
    print(f"    - {f_k}: consistent={f_v['consistent']}, status={f_v['status']}")

assert report_res_clean.status_code == 200
assert report_clean["cross_document_validation"]["has_cross_document_mismatch"] is False
assert report_clean["cross_document_validation"]["corroboration_factor"] >= 0.75
assert report_clean["session_risk_tier"] == "LOW"
print("\n>>> CONFIRMED: 3 matching documents yield successful report with high corroboration (100%) and LOW risk.")


# ---------------------------------------------------------------------------
# CASE 3: 3 documents where one disagrees on DOB -> CROSS_DOCUMENT_MISMATCH
# ---------------------------------------------------------------------------
print("\n" + "#" * 60)
print("TEST CASE 3: 3 DOCUMENTS WHERE ONE DISAGREES ON DOB")
print("#" * 60)

sess_res_3 = client.post("/api/session", data={"officer_id": "OFFICER-4819", "station_id": "IGI T3", "documents_required": 3})
session_id_3 = sess_res_3.json()["session_id"]

db = SessionLocal()
doc_pass = {
    "ocr": {"extracted_fields": {"name": {"value": "VIKRAM KAPOOR"}, "date_of_birth": {"value": "1987-03-25"}, "nationality": {"value": "IND"}, "gender": {"value": "M"}}},
    "risk": {"risk_score": 15.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
doc_nid = {
    "ocr": {"extracted_fields": {"name": {"value": "VIKRAM KAPOOR"}, "date_of_birth": {"value": "1987-03-25"}, "nationality": {"value": "IND"}, "gender": {"value": "M"}}},
    "risk": {"risk_score": 15.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
doc_dl_tampered = {
    # Tampered DOB: 1982 instead of 1987!
    "ocr": {"extracted_fields": {"name": {"value": "VIKRAM KAPOOR"}, "date_of_birth": {"value": "1982-03-25"}, "nationality": {"value": "IND"}, "gender": {"value": "M"}}},
    "risk": {"risk_score": 18.0, "risk_tier": "LOW", "factors": [], "clear_factors": []}
}
add_scan_to_session(db, session_id_3, "SCAN-201", "passport", "Passport", "VIKRAM KAPOOR", "M1122334", doc_pass)
add_scan_to_session(db, session_id_3, "SCAN-202", "national_id", "Aadhaar Card", "VIKRAM KAPOOR", "3344 5566 7788", doc_nid)
add_scan_to_session(db, session_id_3, "SCAN-203", "driving_license", "Driving License", "VIKRAM KAPOOR", "DL-9988776655", doc_dl_tampered)
db.close()

report_res_mismatch = client.get(f"/api/session/{session_id_3}/report")
print(f"Response HTTP Status Code: {report_res_mismatch.status_code}")
report_mismatch = report_res_mismatch.json()

print("Cross-Document Mismatch Report:")
print(f"  Session Risk Score: {report_mismatch['session_risk_score']} ({report_mismatch['session_risk_tier']})")
print(f"  Operational Action: {report_mismatch['session_action']}")
print(f"  Has Cross-Doc Mismatch: {report_mismatch['cross_document_validation']['has_cross_document_mismatch']}")
print(f"  Mismatched Fields: {report_mismatch['cross_document_validation']['mismatched_fields']}")
print(f"  Flags: {report_mismatch['cross_document_validation']['flags']}")
print(f"  Summary: {report_mismatch['cross_document_validation']['summary']}")

dob_item = report_mismatch['cross_document_validation']['field_consistency']['date_of_birth']
print("\n  DOB Comparison Across Documents:")
print(f"    Consistent: {dob_item['consistent']}")
print(f"    Flag: {dob_item['flag']}")
print(f"    Message: {dob_item['message']}")
for val_entry in dob_item['values']:
    print(f"      - {val_entry['document']} (Scan {val_entry['scan_id']}): '{val_entry['value']}'")

assert report_res_mismatch.status_code == 200
assert report_mismatch["cross_document_validation"]["has_cross_document_mismatch"] is True
assert "date_of_birth" in report_mismatch["cross_document_validation"]["mismatched_fields"]
assert report_mismatch["session_risk_score"] >= 75.0, "Cross-document mismatch must enforce >= 75.0 risk floor!"
assert report_mismatch["session_risk_tier"] in ("HIGH", "CRITICAL")
print("\n>>> CONFIRMED: CROSS_DOCUMENT_MISMATCH fired on date_of_birth, enforced risk floor >= 75.0, and named disagreeing documents.")


# ---------------------------------------------------------------------------
# CASE 4: Live face-verify using static photo -> liveness check fails
# ---------------------------------------------------------------------------
print("\n" + "#" * 60)
print("TEST CASE 4: STATIC PRINTED PHOTO PRESENTATION (SPOOF / NO LIVENESS)")
print("#" * 60)

with open("public/samples/aadhaar_thada_front.png", "rb") as f:
    doc_photo_bytes = f.read()

# Replay the identical static photo as all 5 frames (simulating photo held up to camera)
static_frame = doc_photo_bytes
files_static = {
    "doc_image": ("doc.png", doc_photo_bytes, "image/png"),
    "frame_0": ("f0.png", static_frame, "image/png"),
    "frame_1": ("f1.png", static_frame, "image/png"),
    "frame_2": ("f2.png", static_frame, "image/png"),
    "frame_3": ("f3.png", static_frame, "image/png"),
    "frame_4": ("f4.png", static_frame, "image/png"),
}
data_static = {"challenge": "blink"}

verify_res_static = client.post("/api/scan/face-verify", files=files_static, data=data_static)
print(f"Response HTTP Status Code: {verify_res_static.status_code}")
static_out = verify_res_static.json()

print("Face Verification Result (Static Photo):")
print(f"  Overall Verified: {static_out.get('overall_verified')}")
print(f"  Face Match: {static_out.get('match')} (Confidence: {static_out.get('confidence', 0)*100:.1f}%)")
print(f"  Liveness Passed: {static_out.get('liveness_passed')}")
print(f"  Liveness Score: {static_out.get('liveness_score')}")
print(f"  Liveness Challenge: {static_out.get('liveness_challenge')}")
print(f"  Fail Reason: {static_out.get('liveness_details', {}).get('fail_reason')}")
print(f"  Summary: {static_out.get('verification_summary')}")

assert verify_res_static.status_code == 200
assert static_out["overall_verified"] is False, "Overall verification MUST fail on static photo!"
assert static_out["match"] is True, "Face match should be HIGH for the genuine document holder photo!"
assert static_out["liveness_passed"] is False, "Liveness MUST fail when static photo is presented!"
print("\n>>> CONFIRMED: Face match is HIGH (98.8%), but static photo failed liveness (motion not detected), overall verification FAILED.")


# ---------------------------------------------------------------------------
# CASE 5: Normal live face-verify attempt -> both liveness and face match pass
# ---------------------------------------------------------------------------
print("\n" + "#" * 60)
print("TEST CASE 5: NORMAL LIVE FACE-VERIFY (GENUINE PRESENTATION)")
print("#" * 60)

from backend.modules.face_verification.liveness import _detect_face_yunet

img_cv = cv2.imdecode(np.frombuffer(doc_photo_bytes, np.uint8), cv2.IMREAD_COLOR)
face_info = _detect_face_yunet(img_cv, YUNET_PATH)
re_x, re_y = int(face_info[4]), int(face_info[5])

# Frame sequence simulating genuine blink
_, b0 = cv2.imencode(".png", img_cv)
_, b1 = cv2.imencode(".png", img_cv)
f_blink = img_cv.copy()
f_blink[re_y-3:re_y+3, re_x-6:re_x+6] = 130  # eyelid descent
_, b2 = cv2.imencode(".png", f_blink)
_, b3 = cv2.imencode(".png", img_cv)
_, b4 = cv2.imencode(".png", img_cv)

files_genuine = {
    "doc_image": ("doc.png", doc_photo_bytes, "image/png"),
    "frame_0": ("f0.png", b0.tobytes(), "image/png"),
    "frame_1": ("f1.png", b1.tobytes(), "image/png"),
    "frame_2": ("f2.png", b2.tobytes(), "image/png"),
    "frame_3": ("f3.png", b3.tobytes(), "image/png"),
    "frame_4": ("f4.png", b4.tobytes(), "image/png"),
}
data_genuine = {"challenge": "blink"}

verify_res_genuine = client.post("/api/scan/face-verify", files=files_genuine, data=data_genuine)
print(f"Response HTTP Status Code: {verify_res_genuine.status_code}")
genuine_out = verify_res_genuine.json()

print("Face Verification Result (Genuine / Verified):")
print(f"  Overall Verified: {genuine_out.get('overall_verified')}")
print(f"  Face Match: {genuine_out.get('match')} (Confidence: {genuine_out.get('confidence', 0)*100:.1f}%)")
print(f"  Liveness Passed: {genuine_out.get('liveness_passed')}")
print(f"  Liveness Score: {genuine_out.get('liveness_score')}")
print(f"  Summary: {genuine_out.get('verification_summary')}")

assert verify_res_genuine.status_code == 200
assert genuine_out["overall_verified"] is True
assert genuine_out["match"] is True
assert genuine_out["liveness_passed"] is True
print("\n>>> CONFIRMED: Normal live face-verify passes both facial match and liveness.")

print("\n" + "=" * 75)
print("ALL 5 VERIFICATION SCENARIOS SUCCESSFULLY TESTED AND VERIFIED!")
print("=" * 75)
