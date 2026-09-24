"""
dataset_generator.py - Generates the synthetic document evaluation dataset for SentinelAuth.

Builds 80 total synthetic documents (40 clean, 40 tampered):
- 16 PAN Cards (8 clean, 8 tampered)
- 16 Aadhaar Cards (8 clean, 8 tampered with valid Verhoeff digits and simulated signed QR)
- 16 Voter ID Cards (8 clean, 8 tampered)
- 16 Passport Cards (8 clean, 8 tampered with ICAO 9303 TD3 MRZ, country UTO)
- 16 Visa Cards (8 clean, 8 tampered with ICAO 9303 MRV-A MRZ, country UTO)

Tampering operations applied:
1. photo_swap: Splicing alternate portrait
2. text_edit: Varied variants:
   - perfect: Undetectable font/alignment match with valid check digits
   - font_mismatch: Inconsistent stroke width/family
   - misaligned: Vertical baseline shift (2-4 px)
   - checksum_break: Broken Verhoeff or format rules
   - qr_mismatch: Printed text altered while QR retains original data (Aadhaar)
   - mrz_checksum_break: MRZ altered without valid ICAO check digit
   - print_vs_mrz_mismatch: Printed field altered while MRZ retains original data
3. recompression: Low-quality JPEG quantization pass

Manifest is written to data/synthetic_dataset/manifest.json.
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import qrcode

from backend.modules.ocr_extraction.checksums import generate_verhoeff, validate_verhoeff
from backend.modules.ocr_extraction.mrz_parser import _icao_checksum
from backend.modules.qr_signer import generate_signed_qr_payload

DATASET_DIR = os.path.join(BASE_DIR, "data", "synthetic_dataset")
IMAGES_DIR = os.path.join(DATASET_DIR, "images")
MANIFEST_PATH = os.path.join(DATASET_DIR, "manifest.json")


def get_font(size: int = 16, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahomabd.ttf" if bold else "C:/Windows/Fonts/tahoma.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_alternate_font(size: int = 16) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "C:/Windows/Fonts/comic.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_mrz_font(size: int = 21) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "C:/Windows/Fonts/lucon.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _get_face_crops() -> Tuple[Image.Image, Image.Image]:
    pan_path = os.path.join(BASE_DIR, "public", "samples", "pan_kaja.png")
    aadh_path = os.path.join(BASE_DIR, "public", "samples", "aadhaar_srija.png")
    
    face_a = None
    face_b = None
    if os.path.exists(pan_path):
        try:
            face_a = Image.open(pan_path).crop((70, 150, 260, 370)).convert("RGB")
        except Exception:
            pass
    if os.path.exists(aadh_path):
        try:
            face_b = Image.open(aadh_path).crop((25, 20, 130, 140)).convert("RGB")
        except Exception:
            pass

    if face_a is None:
        face_a = Image.new("RGB", (140, 160), color=(220, 230, 242))
        d = ImageDraw.Draw(face_a)
        d.ellipse([35, 25, 105, 95], fill=(160, 140, 125))
        d.ellipse([15, 90, 125, 160], fill=(50, 75, 110))
    if face_b is None:
        face_b = Image.new("RGB", (140, 160), color=(245, 230, 220))
        d = ImageDraw.Draw(face_b)
        d.ellipse([30, 20, 110, 90], fill=(120, 95, 80))
        d.ellipse([10, 85, 130, 160], fill=(130, 45, 45))

    return face_a, face_b


def create_portrait(name_seed: str, w: int = 140, h: int = 160) -> Image.Image:
    face_a, _ = _get_face_crops()
    return face_a.resize((w, h))


def create_alternate_portrait(w: int = 140, h: int = 160) -> Image.Image:
    _, face_b = _get_face_crops()
    return face_b.resize((w, h))


# ---------------------------------------------------------------------------
# Clean Card Generators
# ---------------------------------------------------------------------------

def generate_pan_card(data: Dict[str, str]) -> Image.Image:
    img = Image.new("RGB", (800, 480), color=(240, 245, 255))
    d = ImageDraw.Draw(img)
    # Header bar
    d.rectangle([0, 0, 800, 65], fill=(25, 45, 95))
    d.text((25, 12), "INCOME TAX DEPARTMENT", fill="white", font=get_font(20, bold=True))
    d.text((25, 38), "GOVT. OF INDIA / PERMANENT ACCOUNT NUMBER CARD", fill=(210, 230, 255), font=get_font(13))

    f_label = get_font(13)
    f_val = get_font(16, bold=True)

    # 1. PAN Number
    d.text((40, 85), "Permanent Account Number / PAN:", fill=(100, 100, 100), font=f_label)
    d.text((40, 108), data["pan_number"], fill=(10, 10, 100), font=get_font(24, bold=True))

    # 2. Name
    d.text((40, 158), "Name:", fill=(80, 80, 80), font=f_label)
    d.text((180, 158), data["name"], fill="black", font=f_val)

    # 3. Father's Name
    d.text((40, 240), "Father's Name:", fill=(80, 80, 80), font=f_label)
    d.text((180, 240), data["father_name"], fill="black", font=f_val)

    # 4. Date of Birth
    d.text((40, 325), "Date of Birth:", fill=(80, 80, 80), font=f_label)
    d.text((180, 325), data["date_of_birth"], fill="black", font=f_val)

    # Photo Box
    portrait = create_portrait(data["name"], 140, 160)
    img.paste(portrait, (620, 85))
    d.rectangle([620, 85, 760, 245], outline=(100, 100, 100), width=1)

    # Signature Box
    d.rectangle([620, 275, 760, 325], fill=(250, 250, 252), outline=(150, 150, 150), width=1)
    d.text((645, 292), data["name"].split()[0].lower(), fill=(20, 20, 80), font=get_font(14))

    # Official Emblem
    d.ellipse([340, 10, 380, 50], fill=(200, 170, 70), outline=(255, 255, 255), width=2)
    d.text((352, 22), "GOI", fill=(25, 45, 95), font=get_font(11, bold=True))

    # Signed QR code for PAN card (bottom right)
    pan_qr_payload = {
        "pan": data["pan_number"],
        "name": data["name"],
        "father_name": data["father_name"],
        "dob": data["date_of_birth"],
    }
    signed_pan_qr = generate_signed_qr_payload(pan_qr_payload)
    qr = qrcode.QRCode(box_size=3, border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(signed_pan_qr)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").resize((140, 140))
    img.paste(qr_img, (620, 335))

    return img


def generate_aadhaar_card(data: Dict[str, str]) -> Image.Image:
    img = Image.new("RGB", (850, 520), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    # Header bar
    d.rectangle([0, 0, 850, 60], fill=(220, 50, 35))
    d.text((30, 16), "UNIQUE IDENTIFICATION AUTHORITY OF INDIA - GOVERNMENT OF INDIA", fill="white", font=get_font(16, bold=True))

    f_label = get_font(13)
    f_val = get_font(16, bold=True)

    # 1. Name
    d.text((40, 85), "Name:", fill=(80, 80, 80), font=f_label)
    d.text((160, 85), data["name"], fill="black", font=f_val)

    # 2. DOB
    d.text((40, 160), f"DOB: {data['date_of_birth']}", fill="black", font=f_val)

    # 3. Gender
    d.text((40, 222), f"Gender: {data['gender']}", fill="black", font=f_val)

    # 4. Address
    d.text((40, 285), f"Address: {data['address']}", fill="black", font=get_font(14))

    # 5. Aadhaar Number Band
    d.rectangle([0, 375, 850, 445], fill=(245, 245, 245))
    raw_uid = data["aadhaar_number"].replace(" ", "")
    formatted_uid = f"{raw_uid[0:4]} {raw_uid[4:8]} {raw_uid[8:12]}"
    d.text((260, 390), formatted_uid, fill=(200, 20, 20), font=get_font(28, bold=True))
    d.text((320, 455), "MERA AADHAAR, MERI PEHCHAAN", fill=(100, 100, 100), font=get_font(12))

    # Portrait photo
    portrait = create_portrait(data["name"], 130, 150)
    img.paste(portrait, (460, 80))
    d.rectangle([460, 80, 590, 230], outline=(120, 120, 120), width=1)

    # Simulated Cryptographically Signed Aadhaar Secure QR Code (UIDAI Test Key)
    qr_payload = {
        "name": data["name"],
        "dob": data["date_of_birth"],
        "gender": data["gender"],
        "last4": raw_uid[-4:],
    }
    signed_qr_text = generate_signed_qr_payload(qr_payload)
    qr = qrcode.QRCode(box_size=3, border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(signed_qr_text)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").resize((220, 220))
    img.paste(qr_img, (600, 75))

    return img


def generate_voter_card(data: Dict[str, str]) -> Image.Image:
    img = Image.new("RGB", (800, 500), color=(250, 252, 250))
    d = ImageDraw.Draw(img)
    # Header bar
    d.rectangle([0, 0, 800, 60], fill=(20, 110, 60))
    d.text((25, 12), "ELECTION COMMISSION OF INDIA", fill="white", font=get_font(18, bold=True))
    d.text((25, 36), "ELECTOR PHOTO IDENTITY CARD", fill=(220, 245, 220), font=get_font(13))

    f_label = get_font(13)
    f_val = get_font(16, bold=True)

    # 1. EPIC Number
    d.text((40, 92), f"EPIC NO: {data['epic_number']}", fill=(10, 80, 40), font=get_font(20, bold=True))

    # 2. Name
    d.text((40, 155), "Elector's Name:", fill=(80, 80, 80), font=f_label)
    d.text((200, 155), data["name"], fill="black", font=f_val)

    # 3. Father's Name
    d.text((40, 225), "Father's Name:", fill=(80, 80, 80), font=f_label)
    d.text((200, 225), data["father_name"], fill="black", font=f_val)

    # 4. Gender
    d.text((40, 295), f"Gender: {data['gender']}", fill="black", font=f_val)

    # 5. DOB
    d.text((300, 295), f"DOB: {data['date_of_birth']}", fill="black", font=f_val)

    # Address
    d.text((40, 370), f"Address: {data['address']}", fill="black", font=get_font(13))

    # Photo Box
    portrait = create_portrait(data["name"], 140, 160)
    img.paste(portrait, (600, 80))
    d.rectangle([600, 80, 740, 240], outline=(100, 100, 100), width=1)

    return img


def generate_passport_card(data: Dict[str, str]) -> Image.Image:
    """
    Generates a synthetic ICAO 9303 TD3 Passport Document (880x580).
    Country code: 'UTO' (fictional Utopia test code).
    Bottom 20% contains standard 2-line x 44-char machine readable zone.
    """
    img = Image.new("RGB", (880, 580), color=(248, 246, 240))
    d = ImageDraw.Draw(img)

    # Top Header bar
    d.rectangle([0, 0, 880, 65], fill=(21, 34, 56))
    d.text((25, 12), "UTOPIA - PASSPORT / PASSEPORT", fill=(212, 175, 55), font=get_font(20, bold=True))
    d.text((25, 38), "SYNTHETIC SPECIMEN - FICTIONAL TEST DOCUMENT", fill=(200, 220, 240), font=get_font(12))

    # 1. Passport number (top right)
    d.text((540, 75), "PASSPORT NO. / NO. DU PASSEPORT", fill=(100, 100, 100), font=get_font(12))
    d.text((540, 95), data["passport_number"], fill=(180, 20, 20), font=get_font(24, bold=True))

    # Photo box on left
    portrait = create_portrait(data["surname"], 140, 180)
    img.paste(portrait, (35, 90))
    d.rectangle([35, 90, 175, 270], outline=(120, 120, 120), width=1)

    # 2. Surname
    d.text((200, 135), "Surname / Nom:", fill=(90, 90, 90), font=get_font(12))
    d.text((200, 155), data["surname"], fill="black", font=get_font(18, bold=True))

    # 3. Given names
    d.text((200, 200), "Given Names / Prénoms:", fill=(90, 90, 90), font=get_font(12))
    d.text((200, 220), data["given_names"], fill="black", font=get_font(18, bold=True))

    # 4. Nationality
    d.text((200, 265), "Nationality / Nationalité:", fill=(90, 90, 90), font=get_font(12))
    d.text((200, 285), data["nationality"], fill="black", font=get_font(16, bold=True))

    # 5. DOB
    d.text((380, 265), "Date of birth / Date de naissance:", fill=(90, 90, 90), font=get_font(12))
    d.text((380, 285), data["date_of_birth"], fill="black", font=get_font(16, bold=True))

    # 6. Sex
    d.text((200, 330), "Sex / Sexe:", fill=(90, 90, 90), font=get_font(12))
    d.text((200, 350), data["sex"], fill="black", font=get_font(16, bold=True))

    # 7. Expiry
    d.text((380, 330), "Date of expiry / Date d'expiration:", fill=(90, 90, 90), font=get_font(12))
    d.text((380, 350), data["date_of_expiry"], fill="black", font=get_font(16, bold=True))

    # Specimen security watermark
    d.text((260, 410), "SPECIMEN - UTOPIA TEST DOCUMENT", fill=(210, 215, 225), font=get_font(16, bold=True))

    # 8. MRZ (bottom 20%)
    name_clean = f"{data['surname']}<<{data['given_names'].replace(' ', '<')}"
    l1 = (f"P<UTO{name_clean}" + "<" * 44)[:44]

    doc_num = (data["passport_number"] + "<" * 9)[:9]
    c_doc = str(_icao_checksum(doc_num))

    d_parts = data["date_of_birth"].split("/")
    dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
    c_dob = str(_icao_checksum(dob_yymmdd))

    e_parts = data["date_of_expiry"].split("/")
    exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
    c_exp = str(_icao_checksum(exp_yymmdd))

    opt = "<" * 14
    c_opt = "<"
    comp = str(_icao_checksum(doc_num + c_doc + dob_yymmdd + c_dob + exp_yymmdd + c_exp + opt + c_opt))
    l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{data['sex']}{exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"

    mrz_f = get_mrz_font(21)
    d.rectangle([0, 475, 880, 580], fill=(255, 255, 255))
    d.text((20, 485), l1, fill="black", font=mrz_f)
    d.text((20, 525), l2, fill="black", font=mrz_f)

    return img


def generate_visa_card(data: Dict[str, str]) -> Image.Image:
    """
    Generates a synthetic ICAO 9303 MRV-A Visa Document (880x560).
    Country code: 'UTO' (fictional Utopia test code).
    """
    img = Image.new("RGB", (880, 560), color=(244, 248, 252))
    d = ImageDraw.Draw(img)

    # Header bar
    d.rectangle([0, 0, 880, 60], fill=(27, 77, 62))
    d.text((25, 12), "UTOPIA - VISA / MRV-A", fill="white", font=get_font(20, bold=True))
    d.text((25, 38), "SYNTHETIC SPECIMEN - FICTIONAL ENTRY VISA", fill=(180, 230, 210), font=get_font(12))

    # 1. Visa number
    d.text((510, 75), "VISA NUMBER / NO. DU VISA:", fill=(90, 90, 90), font=get_font(12))
    d.text((510, 95), data["visa_number"], fill=(180, 30, 30), font=get_font(24, bold=True))

    # 2. Name
    full_name = f"{data['surname']}, {data['given_names']}"
    d.text((120, 135), "Name / Nom:", fill=(80, 80, 80), font=get_font(12))
    d.text((120, 155), full_name, fill="black", font=get_font(18, bold=True))

    # 3. Passport number
    d.text((120, 225), "Passport No. / Passeport:", fill=(80, 80, 80), font=get_font(12))
    d.text((120, 245), data["passport_number"], fill="black", font=get_font(16, bold=True))

    # 4. Valid From
    d.text((120, 295), "Valid From / Du:", fill=(80, 80, 80), font=get_font(12))
    d.text((120, 315), data["valid_from"], fill="black", font=get_font(16, bold=True))

    # 5. Expiry
    d.text((120, 365), "Expiry / Until:", fill=(80, 80, 80), font=get_font(12))
    d.text((120, 385), data["date_of_expiry"], fill="black", font=get_font(16, bold=True))

    # Entries & Type & Stay Duration
    d.text((380, 225), "Stay Duration / Durée:", fill=(80, 80, 80), font=get_font(12))
    d.text((380, 245), data.get("stay_duration", "90 DAYS"), fill="black", font=get_font(16, bold=True))

    d.text((380, 295), "Entries / Entrées:", fill=(80, 80, 80), font=get_font(12))
    entry_val = data.get("entry_validation", data.get("entries", "MULTIPLE"))
    d.text((380, 315), entry_val, fill="black", font=get_font(16, bold=True))

    d.text((380, 365), "Type / Catégorie:", fill=(80, 80, 80), font=get_font(12))
    v_type = data.get("visa_type", "TOURIST (V)")
    d.text((380, 385), v_type, fill="black", font=get_font(16, bold=True))

    # Photo box on right
    portrait = create_portrait(data["surname"], 140, 160)
    img.paste(portrait, (680, 140))
    d.rectangle([680, 140, 820, 300], outline=(120, 120, 120), width=1)

    # Specimen security watermark
    d.text((200, 420), "SPECIMEN - UTOPIA ENTRY CLEARANCE", fill=(210, 220, 235), font=get_font(16, bold=True))

    # 6. MRZ
    name_clean = f"{data['surname']}<<{data['given_names'].replace(' ', '<')}"
    l1 = (f"V<UTO{name_clean}" + "<" * 44)[:44]

    v_num = (data["visa_number"] + "<" * 9)[:9]
    c_vnum = str(_icao_checksum(v_num))

    d_parts = data["date_of_birth"].split("/")
    dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
    c_dob = str(_icao_checksum(dob_yymmdd))

    e_parts = data["date_of_expiry"].split("/")
    exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
    c_exp = str(_icao_checksum(exp_yymmdd))

    opt = "<" * 16
    l2 = f"{v_num}{c_vnum}UTO{dob_yymmdd}{c_dob}{data['sex']}{exp_yymmdd}{c_exp}{opt}"

    mrz_f = get_mrz_font(21)
    d.rectangle([0, 460, 880, 560], fill=(255, 255, 255))
    d.text((20, 470), l1, fill="black", font=mrz_f)
    d.text((20, 510), l2, fill="black", font=mrz_f)

    return img


def verify_template_alignment(img: Image.Image, doc_type: str) -> None:
    from backend.modules.ocr_extraction.layout_templates import get_layout_template
    template = get_layout_template(doc_type)
    if not template:
        raise ValueError(f"[verify_template_alignment] No template found for document type: {doc_type}")

    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    for field_name, bbox in template.items():
        ymin, xmin, ymax, xmax = bbox
        if not (0.0 <= ymin < ymax <= 1.0 and 0.0 <= xmin < xmax <= 1.0):
            raise ValueError(
                f"[verify_template_alignment] Field '{field_name}' in {doc_type} has out-of-bounds coordinates: {bbox}"
            )

        y1, y2 = int(ymin * h), int(ymax * h)
        x1, x2 = int(xmin * w), int(xmax * w)
        crop = gray[y1:y2, x1:x2]

        if crop.size == 0:
            raise ValueError(
                f"[verify_template_alignment] Field '{field_name}' in {doc_type} produced empty crop ({y1}:{y2}, {x1}:{x2})"
            )

        std_dev = float(np.std(crop))
        if std_dev < 3.0:
            raise ValueError(
                f"[verify_template_alignment] Field '{field_name}' in {doc_type} is BLANK! "
                f"Pixel std dev = {std_dev:.2f} < 3.0 in crop ({y1}:{y2}, {x1}:{x2})."
            )


# ---------------------------------------------------------------------------
# Tampering Functions
# ---------------------------------------------------------------------------

def apply_photo_swap(img: Image.Image, doc_type: str) -> Tuple[Image.Image, str, List[float], str]:
    tampered = img.copy()
    if doc_type == "national_id_pan":
        alt_portrait = create_alternate_portrait(140, 160)
        tampered.paste(alt_portrait, (620, 85))
        bbox = [round(85 / 480, 3), round(620 / 800, 3), round(245 / 480, 3), round(760 / 800, 3)]
    elif doc_type == "national_id_aadhaar":
        alt_portrait = create_alternate_portrait(130, 150)
        tampered.paste(alt_portrait, (460, 80))
        bbox = [round(80 / 520, 3), round(460 / 850, 3), round(230 / 520, 3), round(590 / 850, 3)]
    elif doc_type == "national_id_voter":
        alt_portrait = create_alternate_portrait(140, 160)
        tampered.paste(alt_portrait, (600, 80))
        bbox = [round(80 / 500, 3), round(600 / 800, 3), round(240 / 500, 3), round(740 / 800, 3)]
    elif doc_type == "passport":
        alt_portrait = create_alternate_portrait(140, 180)
        tampered.paste(alt_portrait, (35, 90))
        bbox = [round(90 / 580, 3), round(35 / 880, 3), round(270 / 580, 3), round(175 / 880, 3)]
    else: # visa
        alt_portrait = create_alternate_portrait(140, 160)
        tampered.paste(alt_portrait, (680, 140))
        bbox = [round(140 / 560, 3), round(680 / 880, 3), round(300 / 560, 3), round(820 / 880, 3)]

    return tampered, "photo", bbox, "Swapped cardholder photo with alternate portrait."


def apply_text_edit(
    img: Image.Image,
    doc_type: str,
    fields: Dict[str, str],
    variant: str = "perfect",
) -> Tuple[Image.Image, Dict[str, str], str, List[float], str, str]:
    """
    Applies controlled text edit tampering producing the exact specified variant:
    - 'perfect': Same font and alignment, valid check digits where applicable (honest limit test)
    - 'font_mismatch': Inconsistent typography
    - 'misaligned': Vertical baseline shift (3px)
    - 'checksum_break': Broken format or checksum rules
    - 'qr_mismatch': Printed text altered while QR retains original data
    - 'mrz_checksum_break': MRZ line edited without valid check digit
    - 'print_vs_mrz_mismatch': Printed field edited while MRZ retains original data
    """
    tampered = img.copy()
    updated_fields = dict(fields)
    alt_f = get_alternate_font(16)
    clean_f = get_font(16, bold=True)
    d = ImageDraw.Draw(tampered)

    # 1. PAN Card Variants
    if doc_type == "national_id_pan":
        if variant == "perfect":
            # Alter DOB with clean matching font
            old_dob = fields["date_of_birth"]
            new_dob = "05/03/1978" if old_dob != "05/03/1978" else "12/04/1985"
            updated_fields["date_of_birth"] = new_dob
            patch = Image.new("RGB", (170, 32), color=(240, 245, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_dob, fill="black", font=clean_f)
            tampered.paste(patch, (180, 322))
            bbox = [round(322 / 480, 3), round(180 / 800, 3), round(354 / 480, 3), round(350 / 800, 3)]
            return tampered, updated_fields, "dob", bbox, f"Altered DOB to {new_dob} (perfect font/position)", "perfect"

        elif variant == "font_mismatch":
            # Alter Name with alternate font
            old_name = fields["name"]
            new_name = "KAPIL DEV SHARMA"
            updated_fields["name"] = new_name
            patch = Image.new("RGB", (240, 32), color=(240, 245, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_name, fill="black", font=alt_f)
            tampered.paste(patch, (180, 155))
            bbox = [round(155 / 480, 3), round(180 / 800, 3), round(187 / 480, 3), round(420 / 800, 3)]
            return tampered, updated_fields, "name", bbox, f"Altered Name to {new_name} with mismatched font", "font_mismatch"

        elif variant == "misaligned":
            # Alter Father Name shifted vertically by 3px
            old_father = fields["father_name"]
            new_father = "ANAND SHARMA"
            updated_fields["father_name"] = new_father
            patch = Image.new("RGB", (220, 32), color=(240, 245, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_father, fill="black", font=clean_f)
            tampered.paste(patch, (180, 243)) # shifted from 240 to 243 (+3px)
            bbox = [round(243 / 480, 3), round(180 / 800, 3), round(275 / 480, 3), round(400 / 800, 3)]
            return tampered, updated_fields, "father_name", bbox, f"Altered Father Name to {new_father} with 3px baseline shift", "misaligned"

        else: # checksum_break
            # Alter 4th character of PAN to invalid entity type 'X'
            old_pan = fields["pan_number"]
            new_pan = old_pan[:3] + "X" + old_pan[4:]
            updated_fields["pan_number"] = new_pan
            patch = Image.new("RGB", (190, 32), color=(240, 245, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_pan, fill=(10, 10, 100), font=get_font(24, bold=True))
            tampered.paste(patch, (40, 105))
            bbox = [round(105 / 480, 3), round(40 / 800, 3), round(137 / 480, 3), round(230 / 800, 3)]
            return tampered, updated_fields, "pan_number", bbox, f"Altered PAN to {new_pan} (invalid holder type 'X')", "checksum_break"

    # 2. Aadhaar Card Variants
    elif doc_type == "national_id_aadhaar":
        if variant == "perfect":
            old_name = fields["name"]
            new_name = "KAPIL DEV SHARMA"
            updated_fields["name"] = new_name
            patch = Image.new("RGB", (240, 30), color=(255, 255, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_name, fill="black", font=clean_f)
            tampered.paste(patch, (160, 85))
            bbox = [round(85 / 520, 3), round(160 / 850, 3), round(115 / 520, 3), round(400 / 850, 3)]
            return tampered, updated_fields, "name", bbox, f"Altered Name to {new_name} (perfect font/position)", "perfect"

        elif variant == "checksum_break":
            # Alter Aadhaar number last digit to corrupt Verhoeff checksum
            old_uid = fields["aadhaar_number"].replace(" ", "")
            last_digit = int(old_uid[-1])
            corrupted_digit = (last_digit + 5) % 10
            new_uid_raw = old_uid[:-1] + str(corrupted_digit)
            new_uid_fmt = f"{new_uid_raw[0:4]} {new_uid_raw[4:8]} {new_uid_raw[8:12]}"
            updated_fields["aadhaar_number"] = new_uid_fmt
            patch = Image.new("RGB", (320, 42), color=(245, 245, 245))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_uid_fmt, fill=(200, 20, 20), font=get_font(28, bold=True))
            tampered.paste(patch, (260, 388))
            bbox = [round(388 / 520, 3), round(260 / 850, 3), round(430 / 520, 3), round(580 / 850, 3)]
            return tampered, updated_fields, "aadhaar_number", bbox, f"Corrupted Aadhaar check digit to break Verhoeff ({new_uid_fmt})", "checksum_break"

        elif variant in ("qr_mismatch", "qr_mismatch_dob"):
            # Alter printed DOB on card while QR code remains original
            old_dob = fields["date_of_birth"]
            new_dob = "01/01/2000" if old_dob != "01/01/2000" else "14/07/1982"
            updated_fields["date_of_birth"] = new_dob
            patch = Image.new("RGB", (220, 30), color=(255, 255, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), f"DOB: {new_dob}", fill="black", font=clean_f)
            tampered.paste(patch, (40, 158))
            bbox = [round(158 / 520, 3), round(40 / 850, 3), round(188 / 520, 3), round(260 / 850, 3)]
            return tampered, updated_fields, "date_of_birth", bbox, f"Altered printed DOB to {new_dob} while QR code contains original DOB", "qr_mismatch"

        elif variant == "qr_mismatch_name":
            # Alter printed Name on card while QR code retains original name
            old_name = fields["name"]
            new_name = "KAPIL DEV SHARMA" if "KAPIL" not in old_name else "AMIT KUMAR VERMA"
            updated_fields["name"] = new_name
            patch = Image.new("RGB", (280, 30), color=(255, 255, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_name, fill="black", font=clean_f)
            tampered.paste(patch, (160, 85))
            bbox = [round(85 / 520, 3), round(160 / 850, 3), round(115 / 520, 3), round(440 / 850, 3)]
            return tampered, updated_fields, "name", bbox, f"Altered printed Name to {new_name} while QR code contains original Name", "qr_mismatch"

        elif variant == "qr_mismatch_gender":
            # Alter printed Gender on card while QR code retains original gender
            old_gender = fields.get("gender", "Male")
            new_gender = "Female" if old_gender == "Male" else "Male"
            updated_fields["gender"] = new_gender
            patch = Image.new("RGB", (180, 30), color=(255, 255, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), f"Gender: {new_gender}", fill="black", font=clean_f)
            tampered.paste(patch, (40, 222))
            bbox = [round(222 / 520, 3), round(40 / 850, 3), round(252 / 520, 3), round(220 / 850, 3)]
            return tampered, updated_fields, "gender", bbox, f"Altered printed Gender to {new_gender} while QR code contains original Gender", "qr_mismatch"

        elif variant == "qr_mismatch_uid":
            # Alter printed Aadhaar number while QR retains original last 4 digits
            old_uid = fields["aadhaar_number"].replace(" ", "")
            new_last4 = "1234" if old_uid[-4:] != "1234" else "8765"
            new_uid_raw = old_uid[:-4] + new_last4
            new_uid_fmt = f"{new_uid_raw[0:4]} {new_uid_raw[4:8]} {new_uid_raw[8:12]}"
            updated_fields["aadhaar_number"] = new_uid_fmt
            patch = Image.new("RGB", (320, 42), color=(245, 245, 245))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_uid_fmt, fill=(200, 20, 20), font=get_font(28, bold=True))
            tampered.paste(patch, (260, 388))
            bbox = [round(388 / 520, 3), round(260 / 850, 3), round(430 / 520, 3), round(580 / 850, 3)]
            return tampered, updated_fields, "aadhaar_number", bbox, f"Altered printed Aadhaar last 4 to {new_last4} while QR retains original {old_uid[-4:]}", "qr_mismatch"

        else: # misaligned
            # Alter Gender line shifted vertically by 3px
            old_gender = fields.get("gender", "Male")
            new_gender = "Female" if old_gender == "Male" else "Male"
            updated_fields["gender"] = new_gender
            patch = Image.new("RGB", (180, 30), color=(255, 255, 255))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), f"Gender: {new_gender}", fill="black", font=clean_f)
            tampered.paste(patch, (40, 225)) # shifted from 222 to 225 (+3px)
            bbox = [round(225 / 520, 3), round(40 / 850, 3), round(255 / 520, 3), round(220 / 850, 3)]
            return tampered, updated_fields, "gender", bbox, f"Altered Gender with 3px baseline shift", "misaligned"

    # 3. Voter ID Variants
    elif doc_type == "national_id_voter":
        if variant == "perfect":
            old_name = fields["name"]
            new_name = "KAPIL DEV SHARMA"
            updated_fields["name"] = new_name
            patch = Image.new("RGB", (240, 30), color=(250, 252, 250))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_name, fill="black", font=clean_f)
            tampered.paste(patch, (200, 152))
            bbox = [round(152 / 500, 3), round(200 / 800, 3), round(182 / 500, 3), round(440 / 800, 3)]
            return tampered, updated_fields, "name", bbox, f"Altered Name to {new_name} (perfect font/position)", "perfect"

        elif variant == "font_mismatch":
            old_father = fields["father_name"]
            new_father = "ANAND SHARMA"
            updated_fields["father_name"] = new_father
            patch = Image.new("RGB", (220, 30), color=(250, 252, 250))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_father, fill="black", font=alt_f)
            tampered.paste(patch, (200, 222))
            bbox = [round(222 / 500, 3), round(200 / 800, 3), round(252 / 500, 3), round(420 / 800, 3)]
            return tampered, updated_fields, "father_name", bbox, f"Altered Father Name to {new_father} with mismatched font", "font_mismatch"

        elif variant == "misaligned":
            old_dob = fields["date_of_birth"]
            new_dob = "01/01/1990"
            updated_fields["date_of_birth"] = new_dob
            patch = Image.new("RGB", (160, 30), color=(250, 252, 250))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), f"DOB: {new_dob}", fill="black", font=clean_f)
            tampered.paste(patch, (300, 298)) # shifted from 295 to 298 (+3px)
            bbox = [round(298 / 500, 3), round(300 / 800, 3), round(328 / 500, 3), round(460 / 800, 3)]
            return tampered, updated_fields, "date_of_birth", bbox, f"Altered DOB to {new_dob} with 3px vertical shift", "misaligned"

        else: # checksum_break
            # Corrupt EPIC format to include invalid letter in digit field
            old_epic = fields["epic_number"]
            new_epic = old_epic[:6] + "X" + old_epic[7:]
            updated_fields["epic_number"] = new_epic
            patch = Image.new("RGB", (220, 32), color=(250, 252, 250))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), f"EPIC NO: {new_epic}", fill=(10, 80, 40), font=get_font(20, bold=True))
            tampered.paste(patch, (40, 88))
            bbox = [round(88 / 500, 3), round(40 / 800, 3), round(120 / 500, 3), round(260 / 800, 3)]
            return tampered, updated_fields, "epic_number", bbox, f"Corrupted EPIC format to {new_epic} (invalid letter in number field)", "checksum_break"

    # 4. Passport Variants
    elif doc_type == "passport":
        if variant == "perfect":
            # Alter expiry date on print AND update MRZ with valid recomputed check digits
            old_exp = fields["date_of_expiry"]
            new_exp = "15/12/2032" if old_exp != "15/12/2032" else "20/11/2034"
            updated_fields["date_of_expiry"] = new_exp

            # 1. Update print
            patch_p = Image.new("RGB", (160, 28), color=(248, 246, 240))
            pd_p = ImageDraw.Draw(patch_p)
            pd_p.text((4, 4), new_exp, fill="black", font=clean_f)
            tampered.paste(patch_p, (380, 348))

            # 2. Recompute valid MRZ Line 2
            doc_num = (fields["passport_number"] + "<" * 9)[:9]
            c_doc = str(_icao_checksum(doc_num))
            d_parts = fields["date_of_birth"].split("/")
            dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
            c_dob = str(_icao_checksum(dob_yymmdd))
            e_parts = new_exp.split("/")
            new_exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
            c_exp = str(_icao_checksum(new_exp_yymmdd))
            opt = "<" * 14
            c_opt = "<"
            comp = str(_icao_checksum(doc_num + c_doc + dob_yymmdd + c_dob + new_exp_yymmdd + c_exp + opt + c_opt))
            new_l2 = f"{doc_num}{c_doc}UTO{dob_yymmdd}{c_dob}{fields['sex']}{new_exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"

            patch_mrz = Image.new("RGB", (840, 30), color=(255, 255, 255))
            pd_mrz = ImageDraw.Draw(patch_mrz)
            pd_mrz.text((0, 0), new_l2, fill="black", font=get_mrz_font(21))
            tampered.paste(patch_mrz, (20, 525))

            bbox = [round(348 / 580, 3), round(380 / 880, 3), round(376 / 580, 3), round(540 / 880, 3)]
            return tampered, updated_fields, "date_of_expiry", bbox, f"Altered Expiry to {new_exp} with recomputed valid MRZ check digits", "perfect"

        elif variant == "mrz_checksum_break":
            # Alter document number in MRZ Line 2 WITHOUT fixing check digit
            old_doc = fields["passport_number"]
            doc_num_bad = old_doc[:-1] + ("9" if old_doc[-1] != "9" else "1")
            doc_num_bad_pad = (doc_num_bad + "<" * 9)[:9]
            # Keep original check digit
            c_doc_orig = str(_icao_checksum((old_doc + "<" * 9)[:9]))

            d_parts = fields["date_of_birth"].split("/")
            dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
            c_dob = str(_icao_checksum(dob_yymmdd))
            e_parts = fields["date_of_expiry"].split("/")
            exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
            c_exp = str(_icao_checksum(exp_yymmdd))
            opt = "<" * 14
            c_opt = "<"
            comp = str(_icao_checksum((old_doc + "<" * 9)[:9] + c_doc_orig + dob_yymmdd + c_dob + exp_yymmdd + c_exp + opt + c_opt))

            bad_l2 = f"{doc_num_bad_pad}{c_doc_orig}UTO{dob_yymmdd}{c_dob}{fields['sex']}{exp_yymmdd}{c_exp}{opt}{c_opt}{comp}"
            patch_mrz = Image.new("RGB", (840, 30), color=(255, 255, 255))
            pd_mrz = ImageDraw.Draw(patch_mrz)
            pd_mrz.text((0, 0), bad_l2, fill="black", font=get_mrz_font(21))
            tampered.paste(patch_mrz, (20, 525))

            bbox = [round(525 / 580, 3), round(20 / 880, 3), round(555 / 580, 3), round(860 / 880, 3)]
            return tampered, updated_fields, "mrz", bbox, "Altered MRZ document number digit without fixing ICAO check digit", "mrz_checksum_break"

        elif variant == "print_vs_mrz_mismatch":
            # Alter printed surname on card while MRZ retains original surname
            old_sur = fields["surname"]
            new_sur = "WILLIAMS" if old_sur != "WILLIAMS" else "DAVIS"
            updated_fields["surname"] = new_sur
            patch = Image.new("RGB", (220, 30), color=(248, 246, 240))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_sur, fill="black", font=get_font(18, bold=True))
            tampered.paste(patch, (200, 153))
            bbox = [round(153 / 580, 3), round(200 / 880, 3), round(183 / 580, 3), round(420 / 880, 3)]
            return tampered, updated_fields, "surname", bbox, f"Altered printed surname to {new_sur} while MRZ retains original {old_sur}", "print_vs_mrz_mismatch"

        else: # default fallback
            old_given = fields["given_names"]
            new_given = "ALEXANDER"
            updated_fields["given_names"] = new_given
            patch = Image.new("RGB", (220, 30), color=(248, 246, 240))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_given, fill="black", font=alt_f)
            tampered.paste(patch, (200, 218))
            bbox = [round(218 / 580, 3), round(200 / 880, 3), round(248 / 580, 3), round(420 / 880, 3)]
            return tampered, updated_fields, "given_names", bbox, f"Altered Given Names with mismatched font", "font_mismatch"

    # 5. Visa Variants
    else:
        if variant == "perfect":
            # Alter visa number on print AND in MRZ with valid check digits
            old_vnum = fields["visa_number"]
            new_vnum = "V99998888" if old_vnum != "V99998888" else "V88887777"
            updated_fields["visa_number"] = new_vnum

            # 1. Update print
            patch_p = Image.new("RGB", (180, 32), color=(244, 248, 252))
            pd_p = ImageDraw.Draw(patch_p)
            pd_p.text((4, 4), new_vnum, fill=(180, 30, 30), font=get_font(24, bold=True))
            tampered.paste(patch_p, (510, 93))

            # 2. Recompute MRZ Line 2
            v_num_pad = (new_vnum + "<" * 9)[:9]
            c_vnum = str(_icao_checksum(v_num_pad))
            d_parts = fields["date_of_birth"].split("/")
            dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
            c_dob = str(_icao_checksum(dob_yymmdd))
            e_parts = fields["date_of_expiry"].split("/")
            exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
            c_exp = str(_icao_checksum(exp_yymmdd))
            opt = "<" * 16
            new_l2 = f"{v_num_pad}{c_vnum}UTO{dob_yymmdd}{c_dob}{fields['sex']}{exp_yymmdd}{c_exp}{opt}"

            patch_mrz = Image.new("RGB", (840, 30), color=(255, 255, 255))
            pd_mrz = ImageDraw.Draw(patch_mrz)
            pd_mrz.text((0, 0), new_l2, fill="black", font=get_mrz_font(21))
            tampered.paste(patch_mrz, (20, 510))

            bbox = [round(93 / 560, 3), round(510 / 880, 3), round(125 / 560, 3), round(690 / 880, 3)]
            return tampered, updated_fields, "visa_number", bbox, f"Altered Visa number to {new_vnum} with valid recomputed MRZ", "perfect"

        elif variant == "mrz_checksum_break":
            # Alter expiry digit in MRZ line 2 without updating check digit
            v_num_pad = (fields["visa_number"] + "<" * 9)[:9]
            c_vnum = str(_icao_checksum(v_num_pad))
            d_parts = fields["date_of_birth"].split("/")
            dob_yymmdd = f"{d_parts[2][2:]}{d_parts[1]}{d_parts[0]}"
            c_dob = str(_icao_checksum(dob_yymmdd))
            e_parts = fields["date_of_expiry"].split("/")
            exp_yymmdd = f"{e_parts[2][2:]}{e_parts[1]}{e_parts[0]}"
            c_exp_orig = str(_icao_checksum(exp_yymmdd))

            # Corrupt expiry date string
            corrupted_exp = exp_yymmdd[:-1] + ("8" if exp_yymmdd[-1] != "8" else "2")
            opt = "<" * 16
            bad_l2 = f"{v_num_pad}{c_vnum}UTO{dob_yymmdd}{c_dob}{fields['sex']}{corrupted_exp}{c_exp_orig}{opt}"

            patch_mrz = Image.new("RGB", (840, 30), color=(255, 255, 255))
            pd_mrz = ImageDraw.Draw(patch_mrz)
            pd_mrz.text((0, 0), bad_l2, fill="black", font=get_mrz_font(21))
            tampered.paste(patch_mrz, (20, 510))

            bbox = [round(510 / 560, 3), round(20 / 880, 3), round(540 / 560, 3), round(860 / 880, 3)]
            return tampered, updated_fields, "mrz", bbox, "Corrupted MRZ expiry digit without updating check digit", "mrz_checksum_break"

        elif variant == "print_vs_mrz_mismatch":
            # Alter printed name while MRZ retains original name
            old_name = f"{fields['surname']}, {fields['given_names']}"
            new_name = "TAYLOR, ROBERT MARK" if "TAYLOR" not in fields["surname"] else "DAVIS, JAMES EDWARD"
            parts = new_name.split(", ")
            updated_fields["surname"] = parts[0]
            updated_fields["given_names"] = parts[1]
            patch = Image.new("RGB", (320, 30), color=(244, 248, 252))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_name, fill="black", font=get_font(18, bold=True))
            tampered.paste(patch, (120, 153))
            bbox = [round(153 / 560, 3), round(120 / 880, 3), round(183 / 560, 3), round(440 / 880, 3)]
            return tampered, updated_fields, "name", bbox, f"Altered printed name to {new_name} while MRZ retains original {old_name}", "print_vs_mrz_mismatch"

        else: # misaligned
            # Alter Valid From with 3px vertical shift
            old_vf = fields["valid_from"]
            new_vf = "01/02/2023"
            updated_fields["valid_from"] = new_vf
            patch = Image.new("RGB", (180, 28), color=(244, 248, 252))
            pd = ImageDraw.Draw(patch)
            pd.text((4, 4), new_vf, fill="black", font=clean_f)
            tampered.paste(patch, (120, 318)) # shifted from 315 to 318 (+3px)
            bbox = [round(318 / 560, 3), round(120 / 880, 3), round(346 / 560, 3), round(300 / 880, 3)]
            return tampered, updated_fields, "valid_from", bbox, f"Altered Valid From with 3px baseline shift", "misaligned"


def apply_recompression(img: Image.Image) -> Tuple[Image.Image, str, List[float], str]:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=28)
    buf.seek(0)
    return Image.open(buf).convert("RGB"), "whole_image", [0.0, 0.0, 1.0, 1.0], "Recompressed image with heavy JPEG quantization (quality=28)."


def apply_camera_capture_simulation(
    img: Image.Image,
    seed: Optional[int] = None,
) -> Image.Image:
    rng = random.Random(seed) if seed is not None else random
    np_rng = np.random.default_rng(seed) if seed is not None else np.random

    w, h = img.size

    # 1. Rotation & Perspective Skew
    angle_deg = rng.uniform(-2.0, 2.0)
    dx0, dy0 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx1, dy1 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx2, dy2 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx3, dy3 = rng.uniform(-6, 6), rng.uniform(-6, 6)

    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    cx, cy = w / 2.0, h / 2.0

    def rotate_pt(x, y):
        nx = cos_a * (x - cx) - sin_a * (y - cy) + cx
        ny = sin_a * (x - cx) + cos_a * (y - cy) + cy
        return nx, ny

    dst_pts = np.float32([
        [rotate_pt(0, 0)[0] + dx0, rotate_pt(0, 0)[1] + dy0],
        [rotate_pt(w, 0)[0] + dx1, rotate_pt(w, 0)[1] + dy1],
        [rotate_pt(w, h)[0] + dx2, rotate_pt(w, h)[1] + dy2],
        [rotate_pt(0, h)[0] + dx3, rotate_pt(0, h)[1] + dy3],
    ])
    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped_arr = cv2.warpPerspective(
        np.array(img), M, (w, h),
        borderMode=cv2.BORDER_REPLICATE,
        flags=cv2.INTER_LINEAR
    )
    warped_img = Image.fromarray(warped_arr)

    # 2. Uneven Lighting
    grad_angle = rng.uniform(0, 2 * math.pi)
    gx = math.cos(grad_angle)
    gy = math.sin(grad_angle)
    xs = np.linspace(-1, 1, w)
    ys = np.linspace(-1, 1, h)
    X, Y = np.meshgrid(xs, ys)
    linear_ramp = (X * gx + Y * gy) * rng.uniform(0.06, 0.14)
    radius = np.sqrt(X ** 2 + Y ** 2) / math.sqrt(2.0)
    vignette = - (radius ** 2) * rng.uniform(0.04, 0.10)
    lighting_field = np.expand_dims(1.0 + linear_ramp + vignette, axis=2)

    arr = np.array(warped_img, dtype=np.float32) * lighting_field
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    lit_img = Image.fromarray(arr)

    # 3. Brightness & Contrast variation
    b_val = rng.uniform(0.88, 1.12)
    c_val = rng.uniform(0.88, 1.12)
    enhanced = ImageEnhance.Brightness(lit_img).enhance(b_val)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(c_val)

    # 4. Mild Defocus / Blur
    blur_mode = rng.choice(["gaussian", "box", "none"])
    if blur_mode == "gaussian":
        sigma = rng.uniform(0.3, 0.7)
        enhanced = enhanced.filter(ImageFilter.GaussianBlur(radius=sigma))
    elif blur_mode == "box":
        enhanced = enhanced.filter(ImageFilter.BoxBlur(radius=1))

    # 5. Gaussian Sensor Noise
    noise_sigma = rng.uniform(1.2, 3.8)
    arr_f = np.array(enhanced, dtype=np.float32)
    noise = np_rng.normal(0, noise_sigma, arr_f.shape)
    noisy_arr = np.clip(arr_f + noise, 0, 255).astype(np.uint8)
    noisy_img = Image.fromarray(noisy_arr)

    # 6. Varied JPEG Recompression
    quality = rng.randint(72, 94)
    buf = io.BytesIO()
    noisy_img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# ---------------------------------------------------------------------------
# Master Dataset Generation Routine (80 Docs Total: 40 Clean, 40 Tampered)
# ---------------------------------------------------------------------------

def generate_dataset(force: bool = False) -> List[Dict[str, Any]]:
    os.makedirs(IMAGES_DIR, exist_ok=True)

    if not force and os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if len(manifest) >= 80:
                print(f"[Dataset] Manifest already exists with {len(manifest)} documents at {MANIFEST_PATH}")
                return manifest
        except Exception:
            pass

    print(f"[Dataset] Generating 80 synthetic documents at {IMAGES_DIR}...")

    # 1. PAN Profiles (8)
    pan_profiles = [
        {"pan_number": "ABCDE1234F", "name": "OM BANSAL", "father_name": "VED BANSAL", "date_of_birth": "12/04/1985"},
        {"pan_number": "BKTPM8912K", "name": "PRIYA NAIR", "father_name": "RAMESH NAIR", "date_of_birth": "22/09/1991"},
        {"pan_number": "CPZAR4410E", "name": "VENKATARAMAN SUBRAMANIAN", "father_name": "KRISHNASWAMY SUBRAMANIAN", "date_of_birth": "05/11/1988"},
        {"pan_number": "DFTPS7731L", "name": "DEEPAK SHARMA", "father_name": "ANAND SHARMA", "date_of_birth": "19/07/1983"},
        {"pan_number": "EAHPA2294M", "name": "SUNITA GUPTA", "father_name": "HARISH GUPTA", "date_of_birth": "30/01/1976"},
        {"pan_number": "FCKPB6605N", "name": "RAJESH KUMAR", "father_name": "SURESH KUMAR", "date_of_birth": "14/06/1995"},
        {"pan_number": "GPLPT1198P", "name": "ANIL AGARWAL", "father_name": "DINESH AGARWAL", "date_of_birth": "08/10/1980"},
        {"pan_number": "HYQPV3321Q", "name": "MEERA IYER", "father_name": "GOPAL IYER", "date_of_birth": "27/03/1993"},
    ]

    # 2. Aadhaar Profiles (8)
    aadhaar_profiles = [
        {"raw_uid": "99994105678", "name": "RAM SEN", "date_of_birth": "15/08/1992", "gender": "Male", "address": "H No 45, Sector 12, Gandhinagar, Gujarat 382016"},
        {"raw_uid": "88882190345", "name": "ROHAN MEHTA", "date_of_birth": "10/02/1986", "gender": "Male", "address": "Flat 204, Galaxy Apt, Andheri, Mumbai 400053"},
        {"raw_uid": "77773412569", "name": "PRIYADARSHINI MUKHERJEE", "date_of_birth": "25/10/1995", "gender": "Female", "address": "12/A Temple St, Mylapore, Chennai 600004"},
        {"raw_uid": "66665510293", "name": "KARTIK RAO", "date_of_birth": "03/05/1990", "gender": "Male", "address": "Plot 88, Jubilee Hills, Hyderabad 500033"},
        {"raw_uid": "55551239847", "name": "DIYA JAIN", "date_of_birth": "18/12/1993", "gender": "Female", "address": "B-12 Navrangpura, Ahmedabad, Gujarat 380009"},
        {"raw_uid": "44449823105", "name": "SANJAY CHOPRA", "date_of_birth": "29/08/1981", "gender": "Male", "address": "House 10, Civil Lines, Jaipur, Rajasthan 302006"},
        {"raw_uid": "33337654129", "name": "ANANTHAKRISHNAN BALASUBRAMANIAM", "date_of_birth": "07/04/1997", "gender": "Male", "address": "5B Park Circus, Kolkata, West Bengal 700017"},
        {"raw_uid": "22228945610", "name": "AJAY TIWARI", "date_of_birth": "12/09/1984", "gender": "Male", "address": "D-44 Gomti Nagar, Lucknow, Uttar Pradesh 226010"},
    ]

    # 3. Voter Profiles (8)
    voter_profiles = [
        {"epic_number": "WBD1234567", "name": "JOY DAS", "father_name": "BIMAL DAS", "gender": "Male", "date_of_birth": "24/09/1980", "address": "Flat 3B, Lake View, Kolkata 700029"},
        {"epic_number": "DEL9876543", "name": "NEHA BANSAL", "father_name": "OM BANSAL", "gender": "Female", "date_of_birth": "11/03/1992", "address": "C-5 Rohini Sector 9, Delhi 110085"},
        {"epic_number": "MAH4567890", "name": "CHANDRASEKHAR VENKATESHWARAN", "father_name": "ASHOK VENKATESHWARAN", "gender": "Male", "date_of_birth": "16/07/1987", "address": "Plot 22 Kothrud, Pune 411038"},
        {"epic_number": "KAR3210987", "name": "KAVYA HEGDE", "father_name": "SUBHASH HEGDE", "gender": "Female", "date_of_birth": "09/11/1994", "address": "4th Cross Indiranagar, Bengaluru 560038"},
        {"epic_number": "TAM6543210", "name": "M RAJ", "father_name": "G RAJ", "gender": "Male", "date_of_birth": "28/05/1983", "address": "77 Anna Salai, Chennai 600002"},
        {"epic_number": "GUJ7890123", "name": "BHAVIK SHAH", "father_name": "KIRIT SHAH", "gender": "Male", "date_of_birth": "14/01/1989", "address": "301 City Center, Surat, Gujarat 395007"},
        {"epic_number": "RAJ8901234", "name": "SHIVENDRA PRATAP SINGH", "father_name": "MAN SINGH", "gender": "Male", "date_of_birth": "23/06/1996", "address": "14 Rajput Colony, Jodhpur 342001"},
        {"epic_number": "UPX9012345", "name": "RAHUL MISHRA", "father_name": "SATISH MISHRA", "gender": "Male", "date_of_birth": "05/12/1985", "address": "88 Hazratganj, Lucknow 226001"},
    ]

    # 4. Passport Profiles (8) - Fictional Country UTO (6 valid 2027-2032, 2 expired 2024-2025)
    passport_profiles = [
        {"passport_number": "U12345678", "surname": "SMITH", "given_names": "ALICE JANE", "nationality": "UTO", "date_of_birth": "12/04/1985", "sex": "F", "date_of_expiry": "10/05/2027"},
        {"passport_number": "U23456789", "surname": "JOHNSON", "given_names": "MICHAEL ROBERT", "nationality": "UTO", "date_of_birth": "22/09/1991", "sex": "M", "date_of_expiry": "15/08/2028"},
        {"passport_number": "U34567890", "surname": "WILLIAMS", "given_names": "EMMA CLAIRE", "nationality": "UTO", "date_of_birth": "05/11/1988", "sex": "F", "date_of_expiry": "20/11/2029"},
        {"passport_number": "U45678901", "surname": "BROWN", "given_names": "DAVID JOHN", "nationality": "UTO", "date_of_birth": "19/07/1983", "sex": "M", "date_of_expiry": "04/04/2030"},
        {"passport_number": "U56789012", "surname": "TAYLOR", "given_names": "SARAH LOUISE", "nationality": "UTO", "date_of_birth": "30/01/1976", "sex": "F", "date_of_expiry": "12/12/2031"},
        {"passport_number": "U67890123", "surname": "DAVIS", "given_names": "JAMES EDWARD", "nationality": "UTO", "date_of_birth": "14/06/1995", "sex": "M", "date_of_expiry": "18/06/2032"},
        {"passport_number": "U78901234", "surname": "MILLER", "given_names": "LUCAS ETHAN", "nationality": "UTO", "date_of_birth": "08/10/1980", "sex": "M", "date_of_expiry": "25/09/2024"},
        {"passport_number": "U89012345", "surname": "WILSON", "given_names": "CHLOE GRACE", "nationality": "UTO", "date_of_birth": "27/03/1993", "sex": "F", "date_of_expiry": "30/03/2025"},
    ]

    # 5. Visa Profiles (8) - Fictional Country UTO (6 valid 2027-2028, 2 expired 2024-2025)
    visa_profiles = [
        {"visa_number": "V10293847", "surname": "SMITH", "given_names": "ALICE JANE", "passport_number": "U12345678", "nationality": "UTO", "date_of_birth": "12/04/1985", "sex": "F", "valid_from": "10/01/2025", "date_of_expiry": "10/01/2027", "visa_type": "TOURIST (V)", "entry_validation": "MULTIPLE", "entries": "MULTIPLE", "stay_duration": "90 DAYS"},
        {"visa_number": "V21304958", "surname": "JOHNSON", "given_names": "MICHAEL ROBERT", "passport_number": "U23456789", "nationality": "UTO", "date_of_birth": "22/09/1991", "sex": "M", "valid_from": "15/02/2025", "date_of_expiry": "15/02/2028", "visa_type": "BUSINESS (B)", "entry_validation": "MULTIPLE", "entries": "MULTIPLE", "stay_duration": "180 DAYS"},
        {"visa_number": "V32415069", "surname": "WILLIAMS", "given_names": "EMMA CLAIRE", "passport_number": "U34567890", "nationality": "UTO", "date_of_birth": "05/11/1988", "sex": "F", "valid_from": "01/03/2024", "date_of_expiry": "01/03/2027", "visa_type": "TOURIST (V)", "entry_validation": "SINGLE", "entries": "SINGLE", "stay_duration": "30 DAYS"},
        {"visa_number": "V43526170", "surname": "BROWN", "given_names": "DAVID JOHN", "passport_number": "U45678901", "nationality": "UTO", "date_of_birth": "19/07/1983", "sex": "M", "valid_from": "20/04/2025", "date_of_expiry": "20/04/2028", "visa_type": "STUDENT (S)", "entry_validation": "MULTIPLE", "entries": "MULTIPLE", "stay_duration": "365 DAYS"},
        {"visa_number": "V54637281", "surname": "TAYLOR", "given_names": "SARAH LOUISE", "passport_number": "U56789012", "nationality": "UTO", "date_of_birth": "30/01/1976", "sex": "F", "valid_from": "11/05/2025", "date_of_expiry": "11/05/2027", "visa_type": "TRANSIT (C)", "entry_validation": "SINGLE", "entries": "SINGLE", "stay_duration": "7 DAYS"},
        {"visa_number": "V65748392", "surname": "DAVIS", "given_names": "JAMES EDWARD", "passport_number": "U67890123", "nationality": "UTO", "date_of_birth": "14/06/1995", "sex": "M", "valid_from": "05/06/2025", "date_of_expiry": "05/06/2028", "visa_type": "EMPLOYMENT (E)", "entry_validation": "MULTIPLE", "entries": "MULTIPLE", "stay_duration": "180 DAYS"},
        {"visa_number": "V76859403", "surname": "MILLER", "given_names": "LUCAS ETHAN", "passport_number": "U78901234", "nationality": "UTO", "date_of_birth": "08/10/1980", "sex": "M", "valid_from": "18/07/2023", "date_of_expiry": "18/07/2024", "visa_type": "TOURIST (V)", "entry_validation": "SINGLE", "entries": "SINGLE", "stay_duration": "30 DAYS"},
        {"visa_number": "V87960514", "surname": "WILSON", "given_names": "CHLOE GRACE", "passport_number": "U89012345", "nationality": "UTO", "date_of_birth": "27/03/1993", "sex": "F", "valid_from": "22/08/2023", "date_of_expiry": "22/08/2025", "visa_type": "DIPLOMATIC (D)", "entry_validation": "MULTIPLE", "entries": "MULTIPLE", "stay_duration": "90 DAYS"},
    ]

    manifest: List[Dict[str, Any]] = []

    # Helper plan for tampered variants per doc type
    pan_variants = [None, None, "perfect", "font_mismatch", "misaligned", "checksum_break", None, None]
    aadhaar_variants = [None, None, "qr_mismatch_dob", "qr_mismatch_name", "qr_mismatch_gender", "qr_mismatch_uid", None, None]
    voter_variants = [None, None, "perfect", "font_mismatch", "misaligned", "checksum_break", None, None]

    # Specific 8 tampered variants for passport & visa:
    # 2 photo_swap, 2 mrz_checksum_break, 2 print_vs_mrz_mismatch, 2 perfect
    passport_ops = ["photo_swap", "photo_swap", "text_edit", "text_edit", "text_edit", "text_edit", "text_edit", "text_edit"]
    passport_variants = ["photo_swap", "photo_swap", "mrz_checksum_break", "mrz_checksum_break", "print_vs_mrz_mismatch", "print_vs_mrz_mismatch", "perfect", "perfect"]

    visa_ops = ["photo_swap", "photo_swap", "text_edit", "text_edit", "text_edit", "text_edit", "text_edit", "text_edit"]
    visa_variants = ["photo_swap", "photo_swap", "mrz_checksum_break", "mrz_checksum_break", "print_vs_mrz_mismatch", "print_vs_mrz_mismatch", "perfect", "perfect"]

    tamper_ops = ["photo_swap", "photo_swap", "text_edit", "text_edit", "text_edit", "text_edit", "recompression", "recompression"]

    def _process_group(
        doc_type: str,
        prefix: str,
        profiles: List[Dict[str, Any]],
        variants_list: List[Optional[str]],
        gen_fn,
        seed_offset: int,
        ops_list: Optional[List[str]] = None,
    ):
        ops = ops_list if ops_list is not None else tamper_ops
        for i, prof in enumerate(profiles, start=1):
            seed = seed_offset + i
            base_clean = gen_fn(prof)
            verify_template_alignment(base_clean, doc_type)

            # Clean counterpart
            clean_img = apply_camera_capture_simulation(base_clean, seed=seed)
            clean_id = f"{prefix}_clean_{i:02d}"
            clean_path = os.path.join(IMAGES_DIR, f"{clean_id}.png")
            clean_img.save(clean_path)

            manifest.append({
                "id": clean_id,
                "file_path": os.path.relpath(clean_path, BASE_DIR).replace("\\", "/"),
                "document_type": doc_type,
                "is_tampered": False,
                "tamper_type": None,
                "tamper_variant": None,
                "tamper_details": None,
                "tampered_field": None,
                "tampered_bbox": None,
                "ground_truth_fields": dict(prof),
            })

            # Tampered counterpart
            t_op = ops[i - 1]
            t_var = variants_list[i - 1]
            t_gt = dict(prof)
            t_detail = ""
            t_field = None
            t_bbox = None

            if t_op == "photo_swap":
                raw_t_img, t_field, t_bbox, t_detail = apply_photo_swap(base_clean, doc_type)
                t_var = "photo_swap"
            elif t_op == "text_edit":
                raw_t_img, t_gt, t_field, t_bbox, t_detail, t_var = apply_text_edit(base_clean, doc_type, prof, variant=t_var)
            else: # recompression
                raw_t_img, t_field, t_bbox, t_detail = apply_recompression(base_clean)
                t_var = "recompression"

            t_img = apply_camera_capture_simulation(raw_t_img, seed=seed)
            is_named_variant = (doc_type in ("passport", "visa") or (t_var and "qr_mismatch" in t_var)) and t_var
            t_label = t_var if is_named_variant else t_op
            if t_label and "qr_mismatch" in t_label:
                t_label = "qr_mismatch"
            t_id = f"{prefix}_tampered_{t_label}_{i:02d}"
            t_path = os.path.join(IMAGES_DIR, f"{t_id}.png")
            t_img.save(t_path)

            manifest.append({
                "id": t_id,
                "file_path": os.path.relpath(t_path, BASE_DIR).replace("\\", "/"),
                "document_type": doc_type,
                "is_tampered": True,
                "tamper_type": t_op,
                "tamper_variant": t_var,
                "tamper_details": t_detail,
                "tampered_field": t_field,
                "tampered_bbox": t_bbox,
                "ground_truth_fields": t_gt,
            })

    # 1. PAN CARDS (16 docs)
    _process_group("national_id_pan", "pan", pan_profiles, pan_variants, generate_pan_card, seed_offset=100)

    # 2. AADHAAR CARDS (16 docs)
    # Formats Aadhaar with valid Verhoeff digits
    aadhaar_valid_profs = []
    for a in aadhaar_profiles:
        valid_uid = generate_verhoeff(a["raw_uid"])
        aadhaar_valid_profs.append({
            "aadhaar_number": f"{valid_uid[0:4]} {valid_uid[4:8]} {valid_uid[8:12]}",
            "name": a["name"],
            "date_of_birth": a["date_of_birth"],
            "gender": a["gender"],
            "address": a["address"],
        })
    _process_group("national_id_aadhaar", "aadhaar", aadhaar_valid_profs, aadhaar_variants, generate_aadhaar_card, seed_offset=300)

    # 3. VOTER ID CARDS (16 docs)
    _process_group("national_id_voter", "voter", voter_profiles, voter_variants, generate_voter_card, seed_offset=500)

    # 4. PASSPORT CARDS (16 docs)
    _process_group("passport", "passport", passport_profiles, passport_variants, generate_passport_card, seed_offset=700, ops_list=passport_ops)

    # 5. VISA CARDS (16 docs)
    _process_group("visa", "visa", visa_profiles, visa_variants, generate_visa_card, seed_offset=900, ops_list=visa_ops)

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[Dataset] Successfully generated {len(manifest)} documents ({len([m for m in manifest if not m['is_tampered']])} clean, {len([m for m in manifest if m['is_tampered']])} tampered).")
    print(f"[Dataset] Manifest saved to: {MANIFEST_PATH}")
    return manifest


if __name__ == "__main__":
    generate_dataset(force=True)
