"""
qr_check.py - Generic QR Verification Module for SentinelAuth.

Implements:
1. Native-resolution QR detection with an escalation ladder:
   (1) Full image as-is
   (2) Grayscale + 2x upscale
   (3) Adaptive threshold
   (4) Quadrant search
2. Performance optimization: decode once, SHA-256 caching, <200ms per doc.
3. Parser registry for (document_type, qr_format):
   - aadhaar_secure_qr: UIDAI simulated RSA-2048 signed QR payload
   - pan_qr: PAN QR payload
   - epic_qr: EPIC voter ID QR payload
   - generic_json: standard JSON payload
4. Cryptographic RSA-2048 signature verification (UIDAI_SIM test key).
5. Cross-check against printed fields from label_anchor (name, dob, gender, last4):
   - Per-character / field confidence gating (CONF_THRESHOLD = 0.80).
   - If confidence < 0.80: do NOT flag tampering, report low confidence / skipped check.
   - If confidence >= 0.80 and mismatch: TAMPERING FLAG.
   - Explainable OCR-B substitutions on names treated as OCR artifacts, not tampering.
6. Config-driven skip for documents without QR (passports, visas).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import zlib
import xml.etree.ElementTree as ET
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

try:
    from pyzbar import pyzbar
    _HAS_PYZBAR = True
except Exception:
    _HAS_PYZBAR = False

from backend.modules.qr_signer import verify_signed_qr_payload
from backend.modules.validation.mrz_checks import CONF_THRESHOLD
from backend.modules.validation.mrz_cross_check import explainable_by_ocr_b
from backend.modules.ocr_extraction.checksums import is_masked_aadhaar
from backend.modules.ocr_extraction.ocr_engine import _easyocr_engine
from backend.modules.ocr_extraction.label_anchor import (
    boxes_from_raw_results,
    extract_fields_cascade,
    get_char_confidences_from_crop,
)

logger = logging.getLogger(__name__)

# Config-driven skip for documents without QR standard
SKIP_QR_DOC_TYPES = {
    "passport",
    "passport_card",
    "visa",
    "mrv_a",
    "td3",
}

# Image SHA-256 result cache
_QR_RESULT_CACHE: Dict[str, Dict[str, Any]] = {}


def _normalize_date_str(d_str: str) -> Optional[str]:
    """Normalizes any date string into standard YYYY-MM-DD."""
    if not d_str:
        return None
    s = d_str.strip()
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", s)
    if m:
        d, mon, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f"{y}-{mon}-{d}"
    m_iso = re.search(r"\b(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\b", s)
    if m_iso:
        y, mon, d = m_iso.group(1), m_iso.group(2).zfill(2), m_iso.group(3).zfill(2)
        return f"{y}-{mon}-{d}"
    return None


def _normalize_gender(g_str: str) -> str:
    """Normalizes gender string to 'M', 'F', or 'X'."""
    if not g_str:
        return ""
    g = g_str.strip().upper()
    if g.startswith("M"):
        return "M"
    if g.startswith("F"):
        return "F"
    return g[:1]


def _get_effective_char_confidence(
    image: Optional[np.ndarray],
    val: str,
    base_conf: float,
    crop_bbox: Optional[Tuple[int, int, int, int]] = None,
) -> float:
    """
    Computes effective field confidence.
    If base_conf >= CONF_THRESHOLD (0.80), returns base_conf.
    If base_conf < CONF_THRESHOLD, evaluates per-character confidence using
    EasyOCR recognizer on the field crop to test if the characters themselves
    were recognized with high confidence (mean >= 0.80).
    """
    if base_conf >= CONF_THRESHOLD:
        return base_conf
    if image is not None and crop_bbox is not None and val:
        y1, y2, x1, x2 = crop_bbox
        h, w = image.shape[:2]
        y1_cl = max(0, min(h, y1))
        y2_cl = max(0, min(h, y2))
        x1_cl = max(0, min(w, x1))
        x2_cl = max(0, min(w, x2))
        if y2_cl > y1_cl and x2_cl > x1_cl:
            crop = image[y1_cl:y2_cl, x1_cl:x2_cl]
            try:
                char_confs = get_char_confidences_from_crop(crop, val)
                if char_confs:
                    return float(sum(char_confs) / len(char_confs))
            except Exception as e:
                logger.debug(f"Per-character confidence evaluation note: {e}")
    return base_conf


# Pixel count above which pyzbar/zbar starts to slow down significantly.
# For high-res phone captures the QR is already large; downscale to this
# before the 2x upscale step so we don't balloon memory.
_PYZBAR_DOWNSCALE_THRESHOLD_PX = 2_000_000  # 2 MP
_PYZBAR_TARGET_LONG_EDGE = 1500            # target long-edge in pixels for downscale


def _try_decode_image(img_arr: np.ndarray, step_label: str = "") -> Optional[str]:
    """
    Attempts to decode a QR code from a numpy image array.
    Tries pyzbar first (if available), then OpenCV QRCodeDetector.
    Logs the outcome of each decoder at INFO level so the pipeline is
    always observable in the server log.
    """
    h, w = img_arr.shape[:2]
    tag = f"[QR/{step_label}] ({w}x{h})" if step_label else f"[QR] ({w}x{h})"

    # 1. pyzbar (zbar backend) — handles dense Aadhaar binary QR reliably
    if _HAS_PYZBAR:
        try:
            barcodes = pyzbar.decode(img_arr)
            if barcodes:
                logger.info(f"{tag} pyzbar found {len(barcodes)} barcode(s): "
                            f"{[str(b.type) for b in barcodes]}")
                for b in barcodes:
                    if b.type in ("QRCODE", "QR") or "QR" in str(b.type).upper():
                        try:
                            result = b.data.decode("utf-8")
                        except UnicodeDecodeError:
                            result = b.data.decode("ISO-8859-1")
                        logger.info(f"{tag} pyzbar QR decoded, payload length={len(result)}")
                        return result
                # non-QR barcode found — return its data anyway
                b0 = barcodes[0]
                try:
                    result = b0.data.decode("utf-8")
                except UnicodeDecodeError:
                    result = b0.data.decode("ISO-8859-1")
                logger.info(f"{tag} pyzbar non-QR barcode ({b0.type}) decoded, "
                            f"payload length={len(result)}")
                return result
            else:
                logger.info(f"{tag} pyzbar: no barcodes found")
        except Exception as e:
            logger.warning(f"{tag} pyzbar raised exception: {e}")
    else:
        logger.debug(f"{tag} pyzbar not available, skipping")

    # 2. OpenCV QRCodeDetector fallback
    try:
        detector = cv2.QRCodeDetector()
        val, pts, _ = detector.detectAndDecode(img_arr)
        if val:
            logger.info(f"{tag} cv2.QRCodeDetector decoded, payload length={len(val)}")
            return val
        else:
            logger.info(f"{tag} cv2.QRCodeDetector: no QR detected")
    except Exception as e:
        logger.warning(f"{tag} cv2.QRCodeDetector raised exception: {e}")

    return None


def decode_qr_escalation(image: np.ndarray) -> Tuple[Optional[str], Optional[str], float, Optional[dict]]:
    """
    Escalation ladder for QR decoding.

    Steps
    ─────
    1.   Full BGR image as-is (covers most hardware captures).
    1b.  Smart-downscale grayscale — only when image > 2 MP.  High-res phone
         photos have QR modules that are already 30-60 px wide; pyzbar's zbar
         backend can actually *fail* on very large inputs due to internal row
         budgets.  Downscale long-edge to ~1500 px before trying again.
    2.   Grayscale + 2x upscale (covers small/low-res scans).
    3.   Adaptive threshold on native-size grayscale (two C values).
    4.   Quadrant search with 2x upscale — focuses on each corner / half of
         the document, which is where the Aadhaar back QR typically lives.

    On failure, runs cv2.QRCodeDetector.detect() to check whether a QR
    pattern is physically present but too small to decode, and returns a
    failure_hint dict with that information.

    Returns (decoded_text, escalation_step_name, elapsed_ms, failure_hint).
    failure_hint is None on success; a dict on failure:
      {
        "qr_pattern_detected": bool,
        "estimated_qr_region": Optional[Tuple[int,int,int,int]],  # x,y,w,h px
        "image_w": int, "image_h": int,
        "resolution_warning": bool,  # True if image is small AND QR too small
      }
    All steps are logged at INFO so the server log shows exactly what ran.
    """
    t0 = time.perf_counter()
    h, w = image.shape[:2]
    total_px = h * w
    logger.info(f"[QR/escalation] START image={w}x{h} ({total_px/1e6:.1f} MP) "
                f"pyzbar={'yes' if _HAS_PYZBAR else 'NO'}")

    # ── Step 1: Full BGR image as-is ──────────────────────────────────────────
    res = _try_decode_image(image, "step1_full_bgr")
    if res:
        elapsed = (time.perf_counter() - t0) * 1000.0
        logger.info(f"[QR/escalation] SUCCESS step=step_1_full_as_is {elapsed:.1f}ms")
        return res, "step_1_full_as_is", elapsed, None

    # Convert to grayscale for all remaining steps
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()

    # ── Step 1b: Smart-downscale (high-res images only) ───────────────────────
    if total_px > _PYZBAR_DOWNSCALE_THRESHOLD_PX:
        scale = _PYZBAR_TARGET_LONG_EDGE / max(h, w)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        gray_ds = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info(f"[QR/escalation] step1b: image >2MP, downscaled to {new_w}x{new_h}")
        res = _try_decode_image(gray_ds, "step1b_downscale")
        if res:
            elapsed = (time.perf_counter() - t0) * 1000.0
            logger.info(f"[QR/escalation] SUCCESS step=step_1b_downscale {elapsed:.1f}ms")
            return res, "step_1b_downscale", elapsed, None
    else:
        logger.info(f"[QR/escalation] step1b: skipped (image <= 2MP)")

    # ── Step 2: Grayscale + 2x upscale (helps small/low-res scans) ───────────
    # Cap the upscale target to avoid allocating multi-GB arrays on large inputs.
    max_upscale_dim = 2000
    up_w = min(w * 2, max_upscale_dim * w // max(w, h))
    up_h = min(h * 2, max_upscale_dim * h // max(w, h))
    gray_2x = cv2.resize(gray, (up_w, up_h), interpolation=cv2.INTER_LINEAR)
    logger.info(f"[QR/escalation] step2: gray 2x → {up_w}x{up_h}")
    res = _try_decode_image(gray_2x, "step2_gray_2x")
    if res:
        elapsed = (time.perf_counter() - t0) * 1000.0
        logger.info(f"[QR/escalation] SUCCESS step=step_2_gray_2x {elapsed:.1f}ms")
        return res, "step_2_gray_2x", elapsed, None

    # ── Step 3: Adaptive threshold (two C values) ─────────────────────────────
    for c_val in (5, 2):
        logger.info(f"[QR/escalation] step3: adaptive threshold C={c_val}")
        try:
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, c_val
            )
            res = _try_decode_image(thresh, f"step3_thresh_c{c_val}")
            if res:
                elapsed = (time.perf_counter() - t0) * 1000.0
                logger.info(f"[QR/escalation] SUCCESS step=step_3_adaptive_thresh_c{c_val} {elapsed:.1f}ms")
                return res, f"step_3_adaptive_thresh_c{c_val}", elapsed, None
        except Exception as e:
            logger.warning(f"[QR/escalation] step3 C={c_val} exception: {e}")

    # ── Step 4: Quadrant search ───────────────────────────────────────────────
    # Aadhaar back QR is typically in the bottom-right quadrant.
    quadrants = [
        ("bottom_right", gray[int(h * 0.45):h,  int(w * 0.45):w]),
        ("top_right",    gray[0:int(h * 0.65),  int(w * 0.45):w]),
        ("bottom_left",  gray[int(h * 0.45):h,  0:int(w * 0.55)]),
        ("top_left",     gray[0:int(h * 0.65),  0:int(w * 0.55)]),
    ]
    for q_name, q_crop in quadrants:
        if q_crop.size == 0:
            logger.info(f"[QR/escalation] step4/{q_name}: empty crop, skipped")
            continue
        qh, qw = q_crop.shape[:2]
        # Upscale quadrant crop, capped to avoid huge arrays
        q_scale = min(2.0, 1600.0 / max(qw, qh))
        q_up = cv2.resize(
            q_crop,
            (max(1, int(qw * q_scale)), max(1, int(qh * q_scale))),
            interpolation=cv2.INTER_LINEAR,
        )
        logger.info(f"[QR/escalation] step4/{q_name}: crop={qw}x{qh} → {q_up.shape[1]}x{q_up.shape[0]}")
        res = _try_decode_image(q_up, f"step4_{q_name}")
        if res:
            elapsed = (time.perf_counter() - t0) * 1000.0
            logger.info(f"[QR/escalation] SUCCESS step=step_4_quadrant_{q_name} {elapsed:.1f}ms")
            return res, f"step_4_quadrant_{q_name}", elapsed, None

    elapsed = (time.perf_counter() - t0) * 1000.0

    # ── Post-failure: detect-only pass to distinguish "no QR present" from
    #    "QR present but too small/blurry to decode" ──────────────────────────
    failure_hint: dict = {"image_w": w, "image_h": h, "qr_pattern_detected": False,
                          "estimated_qr_region": None, "resolution_warning": False}
    try:
        detector = cv2.QRCodeDetector()
        retval, points = detector.detect(gray)
        if retval and points is not None and len(points) > 0:
            pts = points[0].reshape(-1, 2)  # (4, 2)
            xs, ys = pts[:, 0], pts[:, 1]
            rx = int(xs.min()); ry = int(ys.min())
            rw = int(xs.max() - xs.min()); rh = int(ys.max() - ys.min())
            qr_px = max(rw, rh)  # longer side of the detected QR region
            failure_hint["qr_pattern_detected"] = True
            failure_hint["estimated_qr_region"] = (rx, ry, rw, rh)
            # Aadhaar Secure QR needs ~800 px across the QR to decode reliably
            failure_hint["resolution_warning"] = qr_px < 800
            logger.warning(
                f"[QR/escalation] QR PATTERN DETECTED but not decoded: "
                f"region=({rx},{ry}) size={rw}x{rh}px, longer_side={qr_px}px "
                f"({'TOO SMALL — need ~800px' if qr_px < 800 else 'size OK, other decode issue'})"
            )
        else:
            logger.warning(
                f"[QR/escalation] detect-only: NO QR pattern found in image "
                f"(image may not have a QR, or QR is extremely small/obscured)"
            )
    except Exception as e:
        logger.debug(f"[QR/escalation] detect-only pass exception: {e}")

    # Resolution warning for small images that never had step 1b
    if total_px <= _PYZBAR_DOWNSCALE_THRESHOLD_PX:
        failure_hint["resolution_warning"] = True  # flag even if detect didn't find it

    logger.warning(f"[QR/escalation] FAILED — all steps exhausted in {elapsed:.1f}ms; "
                   f"image={w}x{h}, pyzbar={'yes' if _HAS_PYZBAR else 'NO'}, "
                   f"qr_pattern_detected={failure_hint['qr_pattern_detected']}")
    return None, None, elapsed, failure_hint


# ---------------------------------------------------------------------------
# Parser Registry
# ---------------------------------------------------------------------------

def parse_real_uidai_secure_qr(data: Union[str, bytes]) -> Dict[str, Any]:
    """
    Parses real UIDAI Secure QR code (compact binary) or legacy XML barcode.

    1. Base-10 integer string -> int -> to_bytes(big)
    2. zlib.decompress(b, 16 + zlib.MAX_WBITS)
    3. Split on byte 0xFF:
       [0] version
       [1] reference id
       [2] name
       [3] dob (DD-MM-YYYY)
       [4] gender
       [5] care-of
       then address fields:
       [6] district, [7] landmark, [8] house, [9] location, [10] pincode,
       [11] post_office, [12] state, [13] street, [14] subdistrict, [15] vtc
       last 256 bytes = RSA signature
    4. Fallback parser for legacy XML: <PrintLetterBarcodeData uid name dob gender .../>
    5. Returns dict with:
       signature_verified: false, signature_status: "SKIPPED", note: "UIDAI root certificate not configured"
    """
    # 4. Fallback parser for legacy XML
    text_cand = ""
    if isinstance(data, str):
        text_cand = data.strip()
    elif isinstance(data, (bytes, bytearray)):
        try:
            text_cand = data.decode("utf-8", errors="ignore").strip()
        except Exception:
            text_cand = ""

    if "<PrintLetterBarcodeData" in text_cand:
        try:
            m = re.search(r"<PrintLetterBarcodeData[^>]*>", text_cand)
            if m:
                xml_tag = m.group(0)
                if not xml_tag.endswith("/>"):
                    xml_tag = xml_tag.rstrip(">") + "/>"
                elem = ET.fromstring(xml_tag)
                attrs = elem.attrib
                uid = attrs.get("uid", "")
                fields: Dict[str, Any] = {
                    "uid": uid,
                    "name": attrs.get("name"),
                    "gender": attrs.get("gender"),
                    "dob": attrs.get("dob") or attrs.get("yob"),
                    "last4": uid[-4:] if len(uid) >= 4 else None,
                    "care_of": attrs.get("co"),
                    "house": attrs.get("house"),
                    "street": attrs.get("street"),
                    "landmark": attrs.get("lm"),
                    "location": attrs.get("loc"),
                    "vtc": attrs.get("vtc"),
                    "post_office": attrs.get("po"),
                    "district": attrs.get("dist"),
                    "subdistrict": attrs.get("subdist"),
                    "state": attrs.get("state"),
                    "pincode": attrs.get("pc"),
                }
                return {
                    "signature_verified": False,
                    "signature_status": "SKIPPED",
                    "note": "UIDAI root certificate not configured",
                    "format": "uidai_xml",
                    "fields": fields,
                    "data": fields,
                    **fields,
                }
        except Exception as e:
            logger.debug(f"XML Aadhaar barcode parse error: {e}")

    # 1. Base-10 integer string -> int -> to_bytes(big)
    raw_bytes = None
    if isinstance(data, str):
        clean_text = data.strip()
        if clean_text.isdigit() and len(clean_text) > 50:
            try:
                big_int = int(clean_text)
                byte_len = (big_int.bit_length() + 7) // 8
                raw_bytes = big_int.to_bytes(byte_len, "big")
            except Exception:
                raw_bytes = None
        else:
            try:
                raw_bytes = clean_text.encode("latin-1")
            except Exception:
                raw_bytes = None
    elif isinstance(data, (bytes, bytearray)):
        try:
            s = data.decode("ascii").strip()
            if s.isdigit() and len(s) > 50:
                big_int = int(s)
                byte_len = (big_int.bit_length() + 7) // 8
                raw_bytes = big_int.to_bytes(byte_len, "big")
            else:
                raw_bytes = bytes(data)
        except Exception:
            raw_bytes = bytes(data)

    # 2. zlib.decompress(b, 16 + zlib.MAX_WBITS)
    decompressed = None
    if raw_bytes:
        try:
            decompressed = zlib.decompress(raw_bytes, 16 + zlib.MAX_WBITS)
        except Exception:
            try:
                decompressed = zlib.decompress(raw_bytes)
            except Exception:
                try:
                    import gzip
                    decompressed = gzip.decompress(raw_bytes)
                except Exception:
                    decompressed = None

    # Check if decompressed payload is XML
    if decompressed and b"<PrintLetterBarcodeData" in decompressed:
        try:
            dec_str = decompressed.decode("utf-8", errors="replace")
            m = re.search(r"<PrintLetterBarcodeData[^>]*>", dec_str)
            if m:
                xml_tag = m.group(0)
                if not xml_tag.endswith("/>"):
                    xml_tag = xml_tag.rstrip(">") + "/>"
                elem = ET.fromstring(xml_tag)
                attrs = elem.attrib
                uid = attrs.get("uid", "")
                fields = {
                    "uid": uid,
                    "name": attrs.get("name"),
                    "gender": attrs.get("gender"),
                    "dob": attrs.get("dob") or attrs.get("yob"),
                    "last4": uid[-4:] if len(uid) >= 4 else None,
                    "care_of": attrs.get("co"),
                    "house": attrs.get("house"),
                    "street": attrs.get("street"),
                    "landmark": attrs.get("lm"),
                    "location": attrs.get("loc"),
                    "vtc": attrs.get("vtc"),
                    "post_office": attrs.get("po"),
                    "district": attrs.get("dist"),
                    "subdistrict": attrs.get("subdist"),
                    "state": attrs.get("state"),
                    "pincode": attrs.get("pc"),
                }
                return {
                    "signature_verified": False,
                    "signature_status": "SKIPPED",
                    "note": "UIDAI root certificate not configured",
                    "format": "uidai_xml",
                    "fields": fields,
                    "data": fields,
                    **fields,
                }
        except Exception:
            pass

    # 3. Split on byte 0xFF
    if decompressed:
        sig_bytes = None
        if len(decompressed) > 256:
            sig_bytes = decompressed[-256:]
            content = decompressed[:-256]
        else:
            content = decompressed

        parts = content.split(b"\xff")

        def _clean_field(idx: int) -> Optional[str]:
            if idx < len(parts):
                val = parts[idx].decode("utf-8", errors="replace").strip()
                return val if val else None
            return None

        ref_id = _clean_field(1)
        last4 = None
        if ref_id:
            m_l4 = re.search(r"\d{4}", ref_id)
            if m_l4:
                last4 = m_l4.group(0)

        fields = {
            "version": _clean_field(0),
            "reference_id": ref_id,
            "name": _clean_field(2),
            "dob": _clean_field(3),
            "gender": _clean_field(4),
            "care_of": _clean_field(5),
            "district": _clean_field(6),
            "landmark": _clean_field(7),
            "house": _clean_field(8),
            "location": _clean_field(9),
            "pincode": _clean_field(10),
            "post_office": _clean_field(11),
            "state": _clean_field(12),
            "street": _clean_field(13),
            "subdistrict": _clean_field(14),
            "vtc": _clean_field(15),
            "last4": last4,
        }
        return {
            "signature_verified": False,
            "signature_status": "SKIPPED",
            "note": "UIDAI root certificate not configured",
            "format": "uidai_secure_qr",
            "fields": fields,
            "data": fields,
            "signature_bytes": sig_bytes,
            **fields,
        }

    return {
        "signature_verified": False,
        "signature_status": "SKIPPED",
        "note": "UIDAI root certificate not configured",
        "format": "unknown",
        "fields": {},
        "data": {},
    }


class QRParserRegistry:
    """Registry of QR payload parsers by document type and format."""

    @staticmethod
    def parse_aadhaar_secure_qr(qr_text: str) -> Tuple[str, Optional[Dict[str, Any]], str, str]:
        """
        Parses Aadhaar QR payload with support for:
        1. Simulated UIDAI signed envelope (UIDAI_SIM:)
        2. Real UIDAI Secure QR compact binary format (BigInteger -> GZIP/zlib -> 0xFF delimiters)
        3. Legacy XML PrintLetterBarcodeData (attributes: uid, name, gender, yob/dob, etc.)
        4. Plain JSON fallback

        Returns: (signature_status, parsed_dict, signature_note, format_name)
        """
        clean_text = qr_text.strip()

        # 1. Simulated UIDAI RSA-2048 Signed QR
        if clean_text.startswith("UIDAI_SIM:"):
            is_valid, data, expl = verify_signed_qr_payload(clean_text)
            sig_status = "PASSED" if is_valid else "FAILED"
            sig_note = "UIDAI simulated RSA-2048 test key verified" if is_valid else f"RSA signature invalid: {expl}"
            return sig_status, data, sig_note, "uidai_simulated"

        # 2. Real UIDAI Secure QR or legacy XML
        parsed_res = parse_real_uidai_secure_qr(clean_text)
        if parsed_res and parsed_res.get("fields"):
            return (
                parsed_res["signature_status"],
                parsed_res["fields"],
                parsed_res["note"],
                parsed_res["format"],
            )

        # 3. Fallback to plain JSON
        try:
            data = json.loads(clean_text)
            return "SKIPPED", data, "Unsigned simulated JSON QR payload (missing signature envelope)", "generic_json"
        except Exception:
            return "NOT_EVALUATED", None, "Unrecognized Aadhaar QR payload format", "unknown"

    @staticmethod
    def parse_pan_qr(qr_text: str) -> Tuple[str, Optional[Dict[str, Any]], str, str]:
        """Parses PAN QR payload (supports signed envelope or JSON)."""
        clean_text = qr_text.strip()
        if clean_text.startswith("UIDAI_SIM:") or clean_text.startswith("NSDL_SIM:"):
            clean_sub = "UIDAI_SIM:" + clean_text.split(":", 1)[1]
            is_valid, data, expl = verify_signed_qr_payload(clean_sub)
            sig_status = "PASSED" if is_valid else "FAILED"
            sig_note = "NSDL simulated RSA-2048 test key verified" if is_valid else f"RSA signature invalid: {expl}"
            return sig_status, data, sig_note, "nsdl_simulated"
        try:
            data = json.loads(clean_text)
            return "SKIPPED", data, "Unsigned PAN JSON QR", "pan_json"
        except Exception:
            return "NOT_EVALUATED", None, "Unrecognized PAN QR format", "unknown"

    @staticmethod
    def parse_epic_qr(qr_text: str) -> Tuple[str, Optional[Dict[str, Any]], str, str]:
        """Parses Voter ID EPIC QR payload."""
        clean_text = qr_text.strip()
        try:
            data = json.loads(clean_text)
            return "SKIPPED", data, "Unsigned EPIC JSON QR", "epic_json"
        except Exception:
            return "NOT_EVALUATED", None, "Unrecognized EPIC QR format", "unknown"

    @staticmethod
    def parse_generic_json(qr_text: str) -> Tuple[str, Optional[Dict[str, Any]], str, str]:
        """Parses generic JSON QR."""
        clean_text = qr_text.strip()
        try:
            data = json.loads(clean_text)
            return "SKIPPED", data, "Generic JSON payload", "generic_json"
        except Exception:
            return "NOT_EVALUATED", None, "Payload is not valid JSON", "unknown"

    @classmethod
    def parse(cls, qr_text: str, doc_type: str) -> Tuple[str, Optional[Dict[str, Any]], str, str]:
        """Routes payload to the registered parser for document_type."""
        d_type = doc_type.lower()
        if "aadhaar" in d_type:
            return cls.parse_aadhaar_secure_qr(qr_text)
        elif "pan" in d_type:
            return cls.parse_pan_qr(qr_text)
        elif "voter" in d_type or "epic" in d_type:
            return cls.parse_epic_qr(qr_text)
        else:
            return cls.parse_generic_json(qr_text)


# ---------------------------------------------------------------------------
# Main Verification Function
# ---------------------------------------------------------------------------

def verify_document_qr(
    image: np.ndarray,
    document_type: str = "national_id_aadhaar",
    doc_id: str = "",
    printed_fields: Optional[Dict[str, Tuple[str, float]]] = None,
    boxes: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Generic QR Verification Orchestrator:
    1. Checks if document type is configured to skip QR.
    2. Decodes QR using escalation ladder with SHA-256 caching.
    3. Verifies cryptographic RSA-2048 signature if present / configured.
    4. Cross-checks decoded QR against printed fields from label_anchor with
       per-character/field confidence gating (CONF_THRESHOLD = 0.80).
    5. Returns 3-state outcome (VERIFIED, TAMPERED, or NOT_EVALUATED / SKIPPED).
    """
    t_start = time.perf_counter()
    doc_type_norm = document_type.lower().strip()
    h, w = image.shape[:2]
    logger.info(f"[QR/verify] START doc_type='{document_type}' doc_id='{doc_id}' "
                f"image={w}x{h} has_printed_fields={bool(printed_fields)}")

    # 1. Config-driven skip for documents without QR standard
    if doc_type_norm in SKIP_QR_DOC_TYPES or any(s in doc_type_norm for s in ("passport", "visa")):
        logger.info(f"[QR/verify] SKIPPED — doc_type '{document_type}' has no QR standard")
        return {
            "outcome": "SKIPPED",
            "field": None,
            "reason": f"QR check skipped for document type '{document_type}' (no QR standard)",
            "qr_found": False,
            "qr_format": None,
            "signature_verified": False,
            "signature_status": "NOT_APPLICABLE",
            "signature_note": "No QR standard for this document type",
            "raw_payload": None,
            "raw_payload_preview": None,
            "escalation_step": None,
            "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "qr_data": None,
            "printed_fields": {},
            "comparisons": {},
            "ocr_artifacts": [],
        }

    # 2. Check SHA-256 cache
    img_bytes = image.tobytes()
    cache_key = hashlib.sha256(img_bytes).hexdigest()
    if cache_key in _QR_RESULT_CACHE and printed_fields is None:
        logger.info(f"[QR/verify] cache HIT for {doc_id or document_type}")
        cached_res = dict(_QR_RESULT_CACHE[cache_key])
        cached_res["cached"] = True
        return cached_res
    logger.info(f"[QR/verify] cache MISS — running escalation ladder")

    # 3. Decode QR via escalation ladder
    qr_text, step_used, decode_ms, failure_hint = decode_qr_escalation(image)
    if not qr_text:
        # Build a resolution-aware reason string
        hint = failure_hint or {}
        img_w, img_h = hint.get("image_w", w), hint.get("image_h", h)
        qr_detected = hint.get("qr_pattern_detected", False)
        region = hint.get("estimated_qr_region")  # (x, y, rw, rh)
        res_warning = hint.get("resolution_warning", False)

        if qr_detected and region:
            rw, rh = region[2], region[3]
            qr_px = max(rw, rh)
            if qr_px < 800:
                reason = (
                    f"QR pattern detected but not decodable at this resolution "
                    f"(image {img_w}x{img_h}, estimated QR region ~{rw}x{rh}px). "
                    f"Aadhaar Secure QR needs roughly 800px+ across the QR itself. "
                    f"Upload the original photo rather than a screenshot or scan."
                )
            else:
                reason = (
                    f"QR pattern detected (estimated region ~{rw}x{rh}px) but could not be "
                    f"decoded — the QR may be partially obscured, damaged, or use an "
                    f"unsupported encoding. Try a cleaner, higher-contrast capture."
                )
        elif res_warning:
            reason = (
                f"QR not decodable at this resolution (image {img_w}x{img_h}) — "
                f"Aadhaar Secure QR needs roughly 800px+ across the QR itself. "
                f"Upload the original photo rather than a screenshot or low-res scan."
            )
        else:
            reason = (
                f"No QR code detected on this image ({img_w}x{img_h}) after exhausting "
                f"all decoding strategies. If this is the Aadhaar reverse side, ensure "
                f"the QR is visible and upload a higher-resolution capture."
            )

        logger.warning(
            f"[QR/verify] NO QR DECODED for '{doc_id or document_type}' after {decode_ms:.1f}ms — "
            f"qr_detected={qr_detected}, res_warning={res_warning}, reason='{reason[:80]}...'"
        )
        res = {
            "outcome": "NOT_EVALUATED",
            "field": "qr_code",
            "reason": reason,
            "qr_found": False,
            "qr_pattern_detected": qr_detected,
            "estimated_qr_region": region,
            "qr_format": None,
            "signature_verified": False,
            "signature_status": "NOT_EVALUATED",
            "signature_note": "No decodable QR code",
            "raw_payload": None,
            "raw_payload_preview": None,
            "escalation_step": None,
            "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "qr_data": None,
            "printed_fields": {},
            "comparisons": {},
            "ocr_artifacts": [],
        }
        _QR_RESULT_CACHE[cache_key] = res
        return res
    logger.info(f"[QR/verify] QR DECODED via {step_used} in {decode_ms:.1f}ms, "
                f"payload length={len(qr_text)}, first 60 chars: {repr(qr_text[:60])}") 

    # 4. Parse QR and evaluate signature status
    sig_status, qr_data, sig_msg, qr_format = QRParserRegistry.parse(qr_text, doc_type_norm)
    preview_len = min(150, len(qr_text))
    raw_preview = qr_text[:preview_len] + ("..." if len(qr_text) > preview_len else "")

    # Cryptographic signature tampering check
    if sig_status == "FAILED":
        res = {
            "outcome": "TAMPERED",
            "field": "qr_signature",
            "reason": f"Cryptographic RSA signature verification failed on QR code: {sig_msg}",
            "qr_found": True,
            "qr_format": qr_format,
            "signature_verified": False,
            "signature_status": "FAILED",
            "signature_note": sig_msg,
            "raw_payload": qr_text,
            "raw_payload_preview": raw_preview,
            "escalation_step": step_used,
            "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "qr_data": qr_data,
            "printed_fields": {},
            "comparisons": {"signature": {"status": "MISMATCH", "details": sig_msg}},
            "ocr_artifacts": [],
        }
        _QR_RESULT_CACHE[cache_key] = res
        return res

    if not qr_data:
        logger.warning(f"[QR/verify] QR DECODED but payload parse FAILED: {sig_msg} "
                       f"(format={qr_format}, payload_len={len(qr_text)})")
        res = {
            "outcome": "NOT_EVALUATED",
            "field": "qr_payload",
            "reason": f"QR code detected and decoded (format: {qr_format or 'unknown'}), "
                      f"but payload could not be parsed: {sig_msg}",
            "qr_found": True,
            "qr_format": qr_format,
            "signature_verified": (sig_status == "PASSED"),
            "signature_status": sig_status,
            "signature_note": sig_msg,
            "raw_payload": qr_text,
            "raw_payload_preview": raw_preview,
            "escalation_step": step_used,
            "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "qr_data": None,
            "printed_fields": {},
            "comparisons": {},
            "ocr_artifacts": [],
        }
        _QR_RESULT_CACHE[cache_key] = res
        return res

    # 5. Extract printed fields if not provided
    if printed_fields is None:
        h, w = image.shape[:2]
        reader = _easyocr_engine.get_reader("en")
        raw_res = reader.readtext(image)
        boxes = boxes_from_raw_results(raw_res, img_shape=(h, w), image=image)
        full_text = "\n".join(b.text for b in boxes)
        printed_fields, _ = extract_fields_cascade(
            boxes,
            doc_type=doc_type_norm,
            full_text=full_text,
            image=image,
        )

    # 6. Cross-check against printed fields with confidence gating
    ocr_artifacts: List[Dict[str, Any]] = []
    comparisons: Dict[str, Any] = {}
    printed_clean = {k: (v[0] if isinstance(v, (tuple, list)) else v) for k, v in printed_fields.items()}

    # A. Check Date of Birth
    qr_dob = qr_data.get("dob") or qr_data.get("date_of_birth")
    if qr_dob:
        if "date_of_birth" in printed_fields:
            p_val, p_conf = printed_fields["date_of_birth"]
            eff_conf = _get_effective_char_confidence(image, p_val, p_conf, (145, 205, 35, 290))
            norm_qr_dob = _normalize_date_str(qr_dob)
            norm_p_dob = _normalize_date_str(p_val)

            if eff_conf < CONF_THRESHOLD:
                comparisons["date_of_birth"] = {
                    "status": "SKIPPED_LOW_CONFIDENCE",
                    "printed": p_val,
                    "confidence": round(eff_conf, 2),
                    "qr": qr_dob,
                    "details": f"Printed OCR confidence ({eff_conf:.2f}) below threshold {CONF_THRESHOLD}",
                }
            elif norm_qr_dob and norm_p_dob:
                if norm_qr_dob != norm_p_dob:
                    return {
                        "outcome": "TAMPERED",
                        "field": "dob",
                        "reason": f"Date of birth mismatch: printed '{p_val}' ({norm_p_dob}, conf={eff_conf:.2f}) conflicts with QR '{qr_dob}' ({norm_qr_dob})",
                        "qr_found": True,
                        "qr_format": qr_format,
                        "signature_verified": (sig_status == "PASSED"),
                        "signature_status": sig_status,
                        "signature_note": sig_msg,
                        "raw_payload": qr_text,
                        "raw_payload_preview": raw_preview,
                        "escalation_step": step_used,
                        "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
                        "qr_data": qr_data,
                        "printed_fields": printed_clean,
                        "comparisons": {
                            **comparisons,
                            "date_of_birth": {
                                "status": "MISMATCH",
                                "printed": p_val,
                                "qr": qr_dob,
                                "details": f"Printed '{p_val}' ({norm_p_dob}) != QR '{qr_dob}' ({norm_qr_dob})"
                            }
                        },
                        "ocr_artifacts": ocr_artifacts,
                    }
                else:
                    comparisons["date_of_birth"] = {
                        "status": "MATCH",
                        "printed": p_val,
                        "qr": qr_dob,
                        "details": f"Standardized date match: {norm_p_dob}"
                    }
        else:
            comparisons["date_of_birth"] = {
                "status": "NOT_COMPARED",
                "printed": None,
                "qr": qr_dob,
                "details": "Date of birth not detected in printed OCR text"
            }
    else:
        comparisons["date_of_birth"] = {
            "status": "NOT_COMPARED",
            "printed": printed_clean.get("date_of_birth"),
            "qr": None,
            "details": "Date of birth not present in QR code"
        }

    # B. Check Name
    qr_name = qr_data.get("name")
    if qr_name:
        if "name" in printed_fields:
            p_name, p_conf = printed_fields["name"]
            eff_conf = _get_effective_char_confidence(image, p_name, p_conf, (75, 125, 140, 450))
            if eff_conf < CONF_THRESHOLD:
                comparisons["name"] = {
                    "status": "SKIPPED_LOW_CONFIDENCE",
                    "printed": p_name,
                    "confidence": round(eff_conf, 2),
                    "qr": qr_name,
                    "details": f"Printed OCR confidence ({eff_conf:.2f}) below threshold {CONF_THRESHOLD}",
                }
            else:
                name_ok, arts = explainable_by_ocr_b(p_name, qr_name)
                if not name_ok:
                    return {
                        "outcome": "TAMPERED",
                        "field": "name",
                        "reason": f"Name mismatch not explainable by OCR confusion: printed '{p_name}' (conf={eff_conf:.2f}) conflicts with QR '{qr_name}'",
                        "qr_found": True,
                        "qr_format": qr_format,
                        "signature_verified": (sig_status == "PASSED"),
                        "signature_status": sig_status,
                        "signature_note": sig_msg,
                        "raw_payload": qr_text,
                        "raw_payload_preview": raw_preview,
                        "escalation_step": step_used,
                        "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
                        "qr_data": qr_data,
                        "printed_fields": printed_clean,
                        "comparisons": {
                            **comparisons,
                            "name": {
                                "status": "MISMATCH",
                                "printed": p_name,
                                "qr": qr_name,
                                "details": f"Name mismatch: printed '{p_name}' conflicts with QR '{qr_name}'"
                            }
                        },
                        "ocr_artifacts": ocr_artifacts,
                    }
                else:
                    if arts:
                        ocr_artifacts.append({"field": "name", "printed": p_name, "qr": qr_name, "confusions": arts})
                    comparisons["name"] = {
                        "status": "MATCH",
                        "printed": p_name,
                        "qr": qr_name,
                        "details": "Full match" if not arts else f"Matched with OCR artifacts: {', '.join(arts)}"
                    }
        else:
            comparisons["name"] = {
                "status": "NOT_COMPARED",
                "printed": None,
                "qr": qr_name,
                "details": "Name not detected in printed OCR text"
            }
    else:
        comparisons["name"] = {
            "status": "NOT_COMPARED",
            "printed": printed_clean.get("name"),
            "qr": None,
            "details": "Name not present in QR code"
        }

    # C. Check Gender
    qr_gender = qr_data.get("gender")
    if qr_gender:
        if "gender" in printed_fields:
            p_gen, p_conf = printed_fields["gender"]
            eff_conf = _get_effective_char_confidence(image, p_gen, p_conf, (210, 265, 35, 260))
            if eff_conf < CONF_THRESHOLD:
                comparisons["gender"] = {
                    "status": "SKIPPED_LOW_CONFIDENCE",
                    "printed": p_gen,
                    "confidence": round(eff_conf, 2),
                    "qr": qr_gender,
                    "details": f"Printed OCR confidence ({eff_conf:.2f}) below threshold {CONF_THRESHOLD}",
                }
            else:
                norm_p_g = _normalize_gender(p_gen)
                norm_qr_g = _normalize_gender(qr_gender)
                if norm_p_g and norm_qr_g and norm_p_g != norm_qr_g:
                    return {
                        "outcome": "TAMPERED",
                        "field": "gender",
                        "reason": f"Gender mismatch: printed '{p_gen}' ({norm_p_g}, conf={eff_conf:.2f}) conflicts with QR '{qr_gender}' ({norm_qr_g})",
                        "qr_found": True,
                        "qr_format": qr_format,
                        "signature_verified": (sig_status == "PASSED"),
                        "signature_status": sig_status,
                        "signature_note": sig_msg,
                        "raw_payload": qr_text,
                        "raw_payload_preview": raw_preview,
                        "escalation_step": step_used,
                        "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
                        "qr_data": qr_data,
                        "printed_fields": printed_clean,
                        "comparisons": {
                            **comparisons,
                            "gender": {
                                "status": "MISMATCH",
                                "printed": p_gen,
                                "qr": qr_gender,
                                "details": f"Gender mismatch: printed '{norm_p_g}' != QR '{norm_qr_g}'"
                            }
                        },
                        "ocr_artifacts": ocr_artifacts,
                    }
                else:
                    comparisons["gender"] = {
                        "status": "MATCH",
                        "printed": p_gen,
                        "qr": qr_gender,
                        "details": f"Matched gender ({norm_p_g or norm_qr_g})"
                    }
        else:
            comparisons["gender"] = {
                "status": "NOT_COMPARED",
                "printed": None,
                "qr": qr_gender,
                "details": "Gender not detected in printed OCR text"
            }
    else:
        comparisons["gender"] = {
            "status": "NOT_COMPARED",
            "printed": printed_clean.get("gender"),
            "qr": None,
            "details": "Gender not present in QR code"
        }

    # D. Check Aadhaar Last 4 Digits / Number
    qr_last4 = qr_data.get("last4")
    if not qr_last4 and qr_data.get("uid"):
        u_str = str(qr_data["uid"]).replace(" ", "")
        if len(u_str) >= 4:
            qr_last4 = u_str[-4:]

    if qr_last4:
        p_uid = None
        p_conf = 0.0
        if "aadhaar_number" in printed_fields:
            p_uid, p_conf = printed_fields["aadhaar_number"]
        elif "aadhaar_last4" in printed_fields:
            p_uid, p_conf = printed_fields["aadhaar_last4"]

        if p_uid:
            eff_conf = _get_effective_char_confidence(image, p_uid, p_conf, (375, 445, 240, 600))
            if eff_conf < CONF_THRESHOLD:
                comparisons["aadhaar_number"] = {
                    "status": "SKIPPED_LOW_CONFIDENCE",
                    "printed": p_uid,
                    "confidence": round(eff_conf, 2),
                    "qr_last4": qr_last4,
                    "details": f"Printed OCR confidence ({eff_conf:.2f}) below threshold {CONF_THRESHOLD}",
                }
            else:
                masked, m_l4 = is_masked_aadhaar(p_uid)
                if masked and m_l4:
                    p_last4 = m_l4
                else:
                    p_digits = re.sub(r"\D", "", p_uid)
                    p_last4 = p_digits[-4:] if len(p_digits) >= 4 else None

                if not p_last4:
                    comparisons["aadhaar_number"] = {
                        "status": "NOT_COMPARED",
                        "printed": p_uid,
                        "qr_last4": qr_last4,
                        "details": "Could not extract last 4 digits from printed Aadhaar",
                    }
                elif p_last4 != str(qr_last4).strip():
                    return {
                        "outcome": "TAMPERED",
                        "field": "aadhaar_number",
                        "reason": f"Aadhaar last 4 digits mismatch: printed '{p_last4}' (conf={eff_conf:.2f}) conflicts with QR '{qr_last4}'",
                        "qr_found": True,
                        "qr_format": qr_format,
                        "signature_verified": (sig_status == "PASSED"),
                        "signature_status": sig_status,
                        "signature_note": sig_msg,
                        "raw_payload": qr_text,
                        "raw_payload_preview": raw_preview,
                        "escalation_step": step_used,
                        "execution_time_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
                        "qr_data": qr_data,
                        "printed_fields": printed_clean,
                        "comparisons": {
                            **comparisons,
                            "aadhaar_number": {
                                "status": "MISMATCH",
                                "printed_last4": p_last4,
                                "qr_last4": qr_last4,
                                "details": f"Last 4 mismatch: printed '{p_last4}' != QR '{qr_last4}'"
                            }
                        },
                        "ocr_artifacts": ocr_artifacts,
                    }
                else:
                    comparisons["aadhaar_number"] = {
                        "status": "MATCH",
                        "printed_last4": p_last4,
                        "qr_last4": qr_last4,
                        "details": f"Last 4 digits match: {p_last4}"
                    }
        else:
            comparisons["aadhaar_number"] = {
                "status": "NOT_COMPARED",
                "printed": None,
                "qr_last4": qr_last4,
                "details": "Aadhaar number not detected in printed OCR text"
            }
    else:
        comparisons["aadhaar_number"] = {
            "status": "NOT_COMPARED",
            "printed_last4": printed_clean.get("aadhaar_number")[-4:] if printed_clean.get("aadhaar_number") else None,
            "qr_last4": None,
            "details": "Aadhaar last 4 digits not present in QR code"
        }

    total_time_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
    sig_label = "cryptographic signature verified" if sig_status == "PASSED" else f"signature status: {sig_status} ({sig_msg})"
    res = {
        "outcome": "VERIFIED",
        "field": None,
        "reason": f"QR decoded successfully ({step_used}) and printed fields cross-checked ({sig_label})",
        "qr_found": True,
        "qr_format": qr_format,
        "signature_verified": (sig_status == "PASSED"),
        "signature_status": sig_status,
        "signature_note": sig_msg,
        "raw_payload": qr_text,
        "raw_payload_preview": raw_preview,
        "escalation_step": step_used,
        "execution_time_ms": total_time_ms,
        "qr_data": qr_data,
        "printed_fields": printed_clean,
        "comparisons": comparisons,
        "ocr_artifacts": ocr_artifacts,
    }
    _QR_RESULT_CACHE[cache_key] = res
    return res
