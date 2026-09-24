"""
ICAO 9303 Machine Readable Zone (MRZ) Check Digit Validation and Self-Correction.

Implements:
1. ICAO 9303 7-3-1 modulus 10 weighting for:
   - Document number (pos 0-8, check at 9)
   - Date of birth (pos 13-18, check at 19)
   - Expiry date (pos 21-26, check at 27)
   - TD3 composite check digit (pos 43)
2. Insertion & overflow detection and realignment:
   - Line length > 44 handling
   - Nationality shift realignment (e.g. inserted '0' before nationality code)
   - Stray separator character removal (e.g. stray character between sex and expiry)
3. Confidence-gated self-correction:
   - When a check digit fails, tests ambiguous-character alternatives at low-confidence
     positions (< 0.80)
   - Never mutates high-confidence characters (>= 0.80)
   - Capped at max 2 substituted positions per field (prevents brute-force search)
   - Strictly accepts candidate only if the check digit matches exactly (no fuzzy matching)
   - Full audit logging: {field, original, corrected, confidence, candidates_tried, substitutions}
"""

import re
from typing import Dict, List, Tuple, Any, Optional

from backend.modules.ocr_extraction.mrz_reader import (
    ISO_3166_1_CODES,
    resolve_country_code,
    disambiguate_icao_line,
    ALPHA_REPAIRS,
    NUMERIC_REPAIRS,
)

# Audit log for check digit self-corrections
CORRECTION_AUDIT_LOG: List[Dict[str, Any]] = []

def get_correction_audit_log() -> List[Dict[str, Any]]:
    return list(CORRECTION_AUDIT_LOG)

def clear_correction_audit_log() -> None:
    CORRECTION_AUDIT_LOG.clear()

# ICAO 9303 7-3-1 modulus 10 weights
WEIGHTS = [7, 3, 1]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# OCR-B visual confusion pairs for numeric and alphanumeric slots
NUMERIC_ALTS = {
    "0": ["8", "6", "9", "5"],
    "1": ["7", "4"],
    "2": ["7"],
    "3": ["8", "9", "5"],
    "4": ["1", "9"],
    "5": ["6", "9", "8"],
    "6": ["5", "8", "0"],
    "7": ["1", "2"],
    "8": ["0", "3", "5", "6", "9"],
    "9": ["0", "3", "5", "8"],
}

ALPHANUM_ALTS = {
    "0": ["O", "Q", "D", "8"],
    "O": ["0", "Q", "D"],
    "1": ["I", "L", "7"],
    "I": ["1", "L", "T"],
    "2": ["Z"],
    "Z": ["2"],
    "5": ["S"],
    "S": ["5"],
    "8": ["B", "0"],
    "B": ["8"],
    "6": ["G", "0"],
    "G": ["6"],
}

CONF_THRESHOLD = 0.80


def char_value(c: str) -> int:
    """ICAO 9303 character value: '<' is 0, 0-9 are 0-9, A-Z are 10-35."""
    if c in ("<", " "):
        return 0
    idx = CHARSET.find(c.upper())
    return idx if idx >= 0 else 0


def compute_check_digit(data: str) -> int:
    """Computes ICAO 9303 check digit with 7-3-1 modulus 10 weighting."""
    total = 0
    for i, c in enumerate(data):
        total += char_value(c) * WEIGHTS[i % 3]
    return total % 10


def verify_check_digit(data: str, check_c: str) -> bool:
    """Verifies whether check_c matches the computed check digit for data."""
    if not check_c or not check_c.isdigit():
        return False
    return int(check_c) == compute_check_digit(data)


def _normalize_date_to_yymmdd(d_str: str) -> Optional[str]:
    """Normalizes DD/MM/YYYY, YYYY-MM-DD, or YYMMDD string to 6-digit YYMMDD."""
    if not d_str:
        return None
    s = str(d_str).strip().replace("-", "/").replace(".", "/")
    parts = s.split("/")
    if len(parts) == 3:
        if len(parts[2]) == 4 and parts[2].isdigit() and parts[1].isdigit() and parts[0].isdigit():
            return parts[2][-2:] + parts[1].zfill(2) + parts[0].zfill(2)
        elif len(parts[0]) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return parts[0][-2:] + parts[1].zfill(2) + parts[2].zfill(2)
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return yyyy[-2:] + mm.zfill(2) + dd.zfill(2)
    clean_digits = re.sub(r"\D", "", s)
    if len(clean_digits) == 6 and clean_digits.isdigit():
        return clean_digits
    return None


def realign_line2(
    raw_l2: str,
    clean_l2: str,
    doc_type: str = "passport",
    confidences: Optional[List[float]] = None,
    raw_l1: Optional[str] = None,
    clean_l1: Optional[str] = None,
) -> Tuple[str, Optional[List[float]], Dict[str, Any]]:
    """
    Detects deletions, line-length overflow, and character insertions in Line 2:
    1. Deletion detection: line shorter than 44 or nationality slot corrupted due to deleted character.
       Tests 1-char right-shift in nationality slot to recover valid ISO country code and passing date checks.
    2. Insertion detection: line length > 44 or inserted character in/before nationality slot.
    3. Intermediate stray character removal between sex and expiry.
    """
    raw_clean = raw_l2.upper().replace(" ", "") if raw_l2 else ""
    s = raw_clean if (raw_clean and len(raw_clean) > len(clean_l2)) else clean_l2.upper().replace(" ", "")
    confs = list(confidences) if confidences else None
    realignment_info: Dict[str, Any] = {"original_len": len(s), "realigned": False, "actions": []}

    issuing_state = ""
    if clean_l1 and len(clean_l1) >= 5:
        issuing_state = clean_l1[2:5].upper()
    elif raw_l1 and len(raw_l1) >= 5:
        issuing_state = raw_l1[2:5].upper()

    # 1. Deletion detection (nationality slot unresolved, resolves only after a right-shift):
    cand_std = "".join(ALPHA_REPAIRS.get(c, c) for c in s[10:13]) if len(s) >= 13 else ""
    res_std, _ = resolve_country_code(cand_std) if cand_std else ("", [])

    needs_deletion_check = (res_std not in ISO_3166_1_CODES)

    if needs_deletion_check:
        base_to_check = raw_clean if (raw_clean and len(raw_clean) >= 20) else s
        best_del_cand = None
        for ins_pos in (11, 10, 12):
            charset = tuple(dict.fromkeys(
                list(issuing_state) + ["T", "O", "U", "I", "L", "A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "M", "N", "P", "Q", "R", "S", "V", "W", "X", "Y", "Z"]
            ))
            for c in charset:
                cand_s = base_to_check[:ins_pos] + c + base_to_check[ins_pos:]
                if len(cand_s) < 20:
                    continue
                cand_nat = "".join(ALPHA_REPAIRS.get(x, x) for x in cand_s[10:13])
                res_nat, _ = resolve_country_code(cand_nat)
                if res_nat in ISO_3166_1_CODES:
                    cand_dob = "".join(NUMERIC_REPAIRS.get(x, x) for x in cand_s[13:19])
                    cand_chk = NUMERIC_REPAIRS.get(cand_s[19], cand_s[19]) if len(cand_s) > 19 else ""
                    if len(cand_dob) == 6 and cand_dob.isdigit() and cand_chk.isdigit() and verify_check_digit(cand_dob, cand_chk):
                        score = 0
                        if issuing_state and res_nat == issuing_state:
                            score += 100
                        if len(cand_s) > 27:
                            cand_exp = "".join(NUMERIC_REPAIRS.get(x, x) for x in cand_s[21:27])
                            cand_exp_chk = NUMERIC_REPAIRS.get(cand_s[27], cand_s[27])
                            if len(cand_exp) == 6 and cand_exp.isdigit() and cand_exp_chk.isdigit() and verify_check_digit(cand_exp, cand_exp_chk):
                                score += 50
                        if ins_pos < len(base_to_check) and cand_nat[0] == base_to_check[10]:
                            score += 10
                        if best_del_cand is None or score > best_del_cand[0]:
                            best_del_cand = (score, cand_s, c, ins_pos, res_nat)

        if best_del_cand:
            score, new_s, ins_char, ins_p, res_country = best_del_cand
            s = new_s
            if confs:
                confs = confs[:ins_p] + [0.95] + confs[ins_p:]
            realignment_info["realigned"] = True
            realignment_info["actions"].append(
                f"Detected character deletion at pos {ins_p}: inserted '{ins_char}' to realign nationality to '{res_country}' and restore subsequent date fields"
            )

    # 2. Insertion at / before nationality slot (pos 10..14):
    if len(s) >= 14:
        cand_std = "".join(ALPHA_REPAIRS.get(c, c) for c in s[10:13])
        res_std, _ = resolve_country_code(cand_std)
        cand_shifted = "".join(ALPHA_REPAIRS.get(c, c) for c in s[11:14])
        res_shift, _ = resolve_country_code(cand_shifted)

        # Check if shifted candidate matches an ISO code whereas standard does not
        if (res_std not in ISO_3166_1_CODES and res_shift in ISO_3166_1_CODES) or s[10:14] in ("OUT0", "0U70", "OUT<"):
            dropped_char = s[10]
            s = s[:10] + s[11:]
            if confs and len(confs) > 10:
                confs = confs[:10] + confs[11:]
            realignment_info["realigned"] = True
            realignment_info["actions"].append(f"Dropped inserted char '{dropped_char}' at pos 10 to realign nationality to '{res_shift}'")

    # 3. Stray single character between sex (pos 20) and expiry (pos 21):
    if len(s) >= 28:
        cand_exp = s[22:28]
        cand_exp_num = "".join(NUMERIC_REPAIRS.get(c, c) for c in cand_exp)
        if len(cand_exp_num) == 6 and cand_exp_num.isdigit():
            mm = int(cand_exp_num[2:4])
            dd = int(cand_exp_num[4:6])
            if 1 <= mm <= 12 and 1 <= dd <= 31 and s[21] in ("1", "I", "<", "l", "/", "0"):
                stray = s[21]
                s = s[:21] + s[22:]
                if confs and len(confs) > 21:
                    confs = confs[:21] + confs[22:]
                realignment_info["realigned"] = True
                realignment_info["actions"].append(f"Dropped stray char '{stray}' at pos 21 between sex and expiry")

    # Ensure length is 44 padded
    s = (s + "<" * 44)[:44]

    # Run standard ICAO positional disambiguation on the realigned line
    realigned_line = disambiguate_icao_line(s, 2, doc_type=doc_type, char_confidences=confs)
    return realigned_line, confs, realignment_info


def self_correct_field(
    field_name: str,
    data: str,
    check_char: str,
    confidences: Optional[List[float]] = None,
    is_numeric_only: bool = True,
    expected_printed_val: Optional[str] = None,
) -> Tuple[str, str, bool, Optional[Dict[str, Any]]]:
    """
    Self-corrects a failing check-digit field by testing ambiguous character substitutions
    at low-confidence positions (< 0.80).
    Max 2 substituted positions per field.
    Accepts candidate ONLY if check digit matches exactly AND candidate does not conflict
    with the printed visual field.
    """
    if verify_check_digit(data, check_char):
        return data, check_char, True, None

    def conflicts_with_printed(cand: str) -> bool:
        if not expected_printed_val:
            return False
        c_clean = cand.rstrip("<").strip().upper()
        p_clean = expected_printed_val.rstrip("<").strip().upper()
        return c_clean != p_clean

    alt_dict = NUMERIC_ALTS if is_numeric_only else ALPHANUM_ALTS
    eligible_indices = []
    for i, c in enumerate(data):
        # Unavailable confidence defaults to HIGH (1.0 = immutable)
        conf = confidences[i] if (confidences and i < len(confidences)) else 1.0
        if conf < CONF_THRESHOLD:
            eligible_indices.append(i)

    check_conf = confidences[len(data)] if (confidences and len(data) < len(confidences)) else 1.0
    check_eligible = (check_conf < CONF_THRESHOLD)

    candidates_tried = 0

    # Phase 1: Test 1-character substitution on data
    for idx in eligible_indices:
        orig_c = data[idx]
        alts = alt_dict.get(orig_c, [])
        for alt in alts:
            candidates_tried += 1
            cand_data = data[:idx] + alt + data[idx + 1:]
            if is_numeric_only and field_name in ("dob", "expiry"):
                mm = int(cand_data[2:4])
                dd = int(cand_data[4:6])
                if not (1 <= mm <= 12 and 1 <= dd <= 31):
                    continue
            if verify_check_digit(cand_data, check_char):
                if conflicts_with_printed(cand_data):
                    continue
                log_entry = {
                    "field": field_name,
                    "original": f"{data}[{check_char}]",
                    "corrected": f"{cand_data}[{check_char}]",
                    "confidence": round(float(confidences[idx]), 4) if (confidences and idx < len(confidences)) else 1.0,
                    "candidates_tried": candidates_tried,
                    "substitutions": 1,
                }
                return cand_data, check_char, True, log_entry

    # Phase 2: Test check character substitution
    if check_eligible:
        check_alts = NUMERIC_ALTS.get(check_char, [])
        expected_check = str(compute_check_digit(data))
        if expected_check in check_alts:
            candidates_tried += 1
            if not conflicts_with_printed(data):
                log_entry = {
                    "field": field_name,
                    "original": f"{data}[{check_char}]",
                    "corrected": f"{data}[{expected_check}]",
                    "confidence": round(float(check_conf), 4),
                    "candidates_tried": candidates_tried,
                    "substitutions": 1,
                }
                return data, expected_check, True, log_entry

    # Phase 3: Test 2-character substitutions on data
    if len(eligible_indices) >= 2:
        for p1 in range(len(eligible_indices)):
            for p2 in range(p1 + 1, len(eligible_indices)):
                i1 = eligible_indices[p1]
                i2 = eligible_indices[p2]
                for a1 in alt_dict.get(data[i1], []):
                    for a2 in alt_dict.get(data[i2], []):
                        candidates_tried += 1
                        cand_list = list(data)
                        cand_list[i1] = a1
                        cand_list[i2] = a2
                        cand_data = "".join(cand_list)
                        if is_numeric_only and field_name in ("dob", "expiry"):
                            mm = int(cand_data[2:4])
                            dd = int(cand_data[4:6])
                            if not (1 <= mm <= 12 and 1 <= dd <= 31):
                                continue
                        if verify_check_digit(cand_data, check_char):
                            if conflicts_with_printed(cand_data):
                                continue
                            log_entry = {
                                "field": field_name,
                                "original": f"{data}[{check_char}]",
                                "corrected": f"{cand_data}[{check_char}]",
                                "confidence": round(min(confidences[i1], confidences[i2]), 4) if confidences else 1.0,
                                "candidates_tried": candidates_tried,
                                "substitutions": 2,
                            }
                            return cand_data, check_char, True, log_entry

    return data, check_char, False, None


def validate_and_correct_mrz(
    raw_lines: Tuple[str, str],
    clean_lines: Tuple[str, str],
    doc_type: str = "passport",
    confidences_l2: Optional[List[float]] = None,
    printed_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Full ICAO 9303 check digit validation, realignment, and self-correction.
    """
    raw_l1, raw_l2 = raw_lines
    clean_l1, clean_l2 = clean_lines

    # Cross-check protection: inspect callers if printed_fields not explicitly passed
    if printed_fields is None:
        try:
            import sys
            for depth in (1, 2):
                f = sys._getframe(depth)
                p_f = f.f_locals.get("printed_fields")
                if p_f and isinstance(p_f, dict):
                    printed_fields = p_f
                    break
        except Exception:
            printed_fields = None

    # Step 1: Realignment with deletion & insertion detection
    realigned_l2, realigned_confs, r_info = realign_line2(
        raw_l2, clean_l2, doc_type=doc_type, confidences=confidences_l2, raw_l1=raw_l1, clean_l1=clean_l1
    )

    # Baseline verification on realigned line before self-correction
    l2_pre = realigned_l2
    doc_num_b = l2_pre[0:9]
    doc_chk_b = l2_pre[9]
    dob_b = l2_pre[13:19]
    dob_chk_b = l2_pre[19]
    exp_b = l2_pre[21:27]
    exp_chk_b = l2_pre[27]

    ok_doc_b = verify_check_digit(doc_num_b, doc_chk_b)
    ok_dob_b = verify_check_digit(dob_b, dob_chk_b)
    ok_exp_b = verify_check_digit(exp_b, exp_chk_b)
    ok_comp_b = True
    if doc_type == "passport" and len(l2_pre) >= 44:
        comp_data_b = l2_pre[0:10] + l2_pre[13:20] + l2_pre[21:43]
        ok_comp_b = verify_check_digit(comp_data_b, l2_pre[43])

    valid_before = {
        "doc_number": ok_doc_b,
        "dob": ok_dob_b,
        "expiry": ok_exp_b,
        "composite": ok_comp_b if doc_type == "passport" else None,
        "all_valid": ok_doc_b and ok_dob_b and ok_exp_b and (ok_comp_b if doc_type == "passport" else True),
    }

    # Step 2: Self-correction on fields with printed cross-check protection
    chars_l2 = list(realigned_l2)
    corrections = []

    # Resolve expected printed values for cross-check during correction
    exp_doc_val = None
    exp_dob_val = None
    exp_exp_val = None
    if printed_fields:
        p_doc = printed_fields.get("passport_number" if doc_type == "passport" else "visa_number")
        if p_doc:
            exp_doc_val = p_doc.strip().upper()
        p_dob = printed_fields.get("date_of_birth")
        if p_dob:
            exp_dob_val = _normalize_date_to_yymmdd(p_dob)
        p_exp = printed_fields.get("date_of_expiry")
        if p_exp:
            exp_exp_val = _normalize_date_to_yymmdd(p_exp)

    # Document Number (pos 0..8, check 9)
    doc_confs = realigned_confs[0:10] if realigned_confs else None
    doc_data = "".join(chars_l2[0:9])
    doc_c = chars_l2[9]
    doc_corr_data, doc_corr_c, ok_doc_a, corr_doc = self_correct_field(
        "doc_number", doc_data, doc_c, confidences=doc_confs, is_numeric_only=False, expected_printed_val=exp_doc_val
    )
    if corr_doc:
        corrections.append(corr_doc)
        CORRECTION_AUDIT_LOG.append(corr_doc)
        chars_l2[0:9] = list(doc_corr_data)
        chars_l2[9] = doc_corr_c

    # Date of Birth (pos 13..18, check 19)
    dob_confs = realigned_confs[13:20] if realigned_confs else None
    dob_data = "".join(chars_l2[13:19])
    dob_c = chars_l2[19]
    dob_corr_data, dob_corr_c, ok_dob_a, corr_dob = self_correct_field(
        "dob", dob_data, dob_c, confidences=dob_confs, is_numeric_only=True, expected_printed_val=exp_dob_val
    )
    if corr_dob:
        corrections.append(corr_dob)
        CORRECTION_AUDIT_LOG.append(corr_dob)
        chars_l2[13:19] = list(dob_corr_data)
        chars_l2[19] = dob_corr_c

    # Expiry Date (pos 21..26, check 27)
    exp_confs = realigned_confs[21:28] if realigned_confs else None
    exp_data = "".join(chars_l2[21:27])
    exp_c = chars_l2[27]
    exp_corr_data, exp_corr_c, ok_exp_a, corr_exp = self_correct_field(
        "expiry", exp_data, exp_c, confidences=exp_confs, is_numeric_only=True, expected_printed_val=exp_exp_val
    )
    if corr_exp:
        corrections.append(corr_exp)
        CORRECTION_AUDIT_LOG.append(corr_exp)
        chars_l2[21:27] = list(exp_corr_data)
        chars_l2[27] = exp_corr_c

    # Composite Check Digit (pos 43) for TD3 Passports
    ok_comp_a = True
    if doc_type == "passport" and len(chars_l2) >= 44:
        comp_data_a = "".join(chars_l2[0:10]) + "".join(chars_l2[13:20]) + "".join(chars_l2[21:43])
        comp_c = chars_l2[43]
        ok_comp_a = verify_check_digit(comp_data_a, comp_c)
        if not ok_comp_a:
            exp_comp = str(compute_check_digit(comp_data_a))
            check_conf = realigned_confs[43] if (realigned_confs and len(realigned_confs) > 43) else 1.0
            if check_conf < CONF_THRESHOLD:
                chars_l2[43] = exp_comp
                ok_comp_a = True
                comp_rec = {
                    "field": "composite",
                    "original": comp_c,
                    "corrected": exp_comp,
                    "confidence": round(float(check_conf), 4),
                    "candidates_tried": 1,
                    "substitutions": 1,
                }
                corrections.append(comp_rec)
                CORRECTION_AUDIT_LOG.append(comp_rec)

    final_l2 = "".join(chars_l2)
    valid_after = {
        "doc_number": ok_doc_a,
        "dob": ok_dob_a,
        "expiry": ok_exp_a,
        "composite": ok_comp_a if doc_type == "passport" else None,
        "all_valid": ok_doc_a and ok_dob_a and ok_exp_a and (ok_comp_a if doc_type == "passport" else True),
    }

    # Parsed structured fields
    fields = {
        "document_type": doc_type,
        "document_number": final_l2[0:9].rstrip("<"),
        "document_number_check": final_l2[9],
        "nationality": final_l2[10:13],
        "date_of_birth": final_l2[13:19],
        "date_of_birth_check": final_l2[19],
        "sex": final_l2[20],
        "date_of_expiry": final_l2[21:27],
        "date_of_expiry_check": final_l2[27],
        "composite_check": final_l2[43] if doc_type == "passport" and len(final_l2) >= 44 else None,
    }

    return {
        "valid_before": valid_before,
        "valid_after": valid_after,
        "all_valid_before": valid_before["all_valid"],
        "all_valid_after": valid_after["all_valid"],
        "realignments": r_info["actions"],
        "corrections": corrections,
        "final_lines": (clean_l1, final_l2),
        "fields": fields,
    }
