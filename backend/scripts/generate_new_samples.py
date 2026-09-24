import os
import qrcode
from PIL import Image, ImageDraw, ImageFont
from backend.modules.ocr_extraction.checksums import generate_verhoeff, validate_verhoeff

OUTPUT_DIR = 'backend/data/sample_documents'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Generate a valid Verhoeff 12-digit Aadhaar number
valid_aadhaar_digits = generate_verhoeff('99994105678')
print('Generated valid Aadhaar number:', valid_aadhaar_digits, 'Valid?', validate_verhoeff(valid_aadhaar_digits))
aadhaar_formatted = f"{valid_aadhaar_digits[0:4]} {valid_aadhaar_digits[4:8]} {valid_aadhaar_digits[8:12]}"

def get_font(size=16):
    candidates = ['C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/tahoma.ttf']
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# 1. SPECIMEN PAN CARD
img_pan = Image.new('RGB', (800, 480), color=(240, 245, 255))
d = ImageDraw.Draw(img_pan)
d.rectangle([0, 0, 800, 65], fill=(25, 45, 95))
d.text((25, 12), 'INCOME TAX DEPARTMENT', fill='white', font=get_font(20))
d.text((25, 38), 'GOVT. OF INDIA / PERMANENT ACCOUNT NUMBER CARD', fill=(210, 230, 255), font=get_font(13))

f = get_font(16)
d.text((40, 95), 'Permanent Account Number / PAN:', fill=(100, 100, 100), font=get_font(13))
d.text((40, 120), 'ABCDE1234F', fill=(10, 10, 100), font=get_font(26))

d.text((40, 180), 'Name:', fill=(80, 80, 80), font=f)
d.text((180, 180), 'RAJESH VERMA', fill='black', font=f)

d.text((40, 230), "Father's Name:", fill=(80, 80, 80), font=f)
d.text((180, 230), 'SURESH VERMA', fill='black', font=f)

d.text((40, 280), 'Date of Birth:', fill=(80, 80, 80), font=f)
d.text((180, 280), '12/04/1985', fill='black', font=f)

d.rectangle([620, 85, 760, 235], outline=(120, 120, 120), width=2)
d.text((660, 150), 'PHOTO', fill=(150, 150, 150), font=get_font(14))
d.rectangle([620, 260, 760, 310], outline=(150, 150, 150), width=1)
d.text((650, 278), 'SIGNATURE', fill=(150, 150, 150), font=get_font(11))

img_pan.save(os.path.join(OUTPUT_DIR, 'specimen_pan_card.png'))
print('Created specimen_pan_card.png')

# 2. SPECIMEN AADHAAR CARD (with QR code pattern)
img_aadh = Image.new('RGB', (850, 520), color=(255, 255, 255))
d = ImageDraw.Draw(img_aadh)
d.rectangle([0, 0, 850, 60], fill=(220, 50, 35))
d.text((30, 16), 'UNIQUE IDENTIFICATION AUTHORITY OF INDIA - GOVERNMENT OF INDIA', fill='white', font=get_font(16))

d.text((40, 90), 'Name:', fill=(80, 80, 80), font=f)
d.text((160, 90), 'SUNITA SHARMA', fill='black', font=f)

d.text((40, 135), 'DOB: 15/08/1992', fill='black', font=f)
d.text((40, 175), 'Gender: Female', fill='black', font=f)

d.text((40, 215), 'Address: H No 45, Sector 12, Gandhinagar, Gujarat 382016', fill='black', font=f)

d.rectangle([0, 380, 850, 440], fill=(245, 245, 245))
d.text((260, 390), aadhaar_formatted, fill=(200, 20, 20), font=get_font(28))
d.text((320, 450), 'MERA AADHAAR, MERI PEHCHAAN', fill=(100, 100, 100), font=get_font(12))

# Genuine readable QR code embedding
qr_xml = f'<PrintLetterBarcodeData uid="{valid_aadhaar_digits}" name="SUNITA SHARMA" gender="F" dob="15/08/1992" house="H No 45" street="Sector 12" vtc="Gandhinagar" state="Gujarat" pc="382016" />'
qr = qrcode.QRCode(box_size=4, border=2)
qr.add_data(qr_xml)
qr.make(fit=True)
qr_img = qr.make_image(fill_color="black", back_color="white").resize((170, 170))
img_aadh.paste(qr_img, (640, 85))

img_aadh.save(os.path.join(OUTPUT_DIR, 'specimen_aadhaar_card.png'))
print('Created specimen_aadhaar_card.png with readable QR code')


# 3. SPECIMEN VOTER ID (EPIC)
img_voter = Image.new('RGB', (800, 500), color=(250, 252, 250))
d = ImageDraw.Draw(img_voter)
d.rectangle([0, 0, 800, 60], fill=(20, 110, 60))
d.text((25, 12), 'ELECTION COMMISSION OF INDIA', fill='white', font=get_font(18))
d.text((25, 36), 'ELECTOR PHOTO IDENTITY CARD', fill=(220, 245, 220), font=get_font(13))

d.text((40, 85), 'EPIC NO: WBD1234567', fill=(10, 80, 40), font=get_font(20))

d.text((40, 135), "Elector's Name:", fill=(80, 80, 80), font=f)
d.text((200, 135), 'AMIT CHATTERJEE', fill='black', font=f)

d.text((40, 180), "Father's Name:", fill=(80, 80, 80), font=f)
d.text((200, 180), 'BIMAL CHATTERJEE', fill='black', font=f)

d.text((40, 225), 'Gender: Male', fill='black', font=f)
d.text((200, 225), 'Date of Birth: 24/09/1980', fill='black', font=f)

d.text((40, 270), 'Address: Flat 3B, Lake View Apartments, Kolkata, West Bengal 700029', fill='black', font=f)

d.rectangle([610, 85, 750, 235], outline=(100, 100, 100), width=2)
d.text((650, 150), 'PHOTO', fill=(150, 150, 150), font=get_font(14))

img_voter.save(os.path.join(OUTPUT_DIR, 'specimen_voter_id.png'))
print('Created specimen_voter_id.png')
