"""
checksums.py - Algorithmic validators for document IDs.
Includes Verhoeff algorithm (used by UIDAI for Aadhaar),
PAN card format regex validator, and EPIC (Voter ID) format validator.
"""
from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Verhoeff Algorithm Constants
# ---------------------------------------------------------------------------

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def validate_verhoeff(number_str: str) -> bool:
    """
    Validate a number using the Verhoeff checksum algorithm (used by Aadhaar/UIDAI).
    Validates any digit string processed right-to-left.
    Tested against standard vector: '2363' -> True, '2364' -> False.
    """
    digits = re.sub(r"\D", "", str(number_str or ""))
    if not digits:
        return False

    c = 0
    for i, item in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(item)]]

    return c == 0


def generate_verhoeff(number_str: str) -> str:
    """Compute and append the Verhoeff check digit to an N-digit prefix."""
    digits = re.sub(r"\D", "", str(number_str or ""))
    if not digits:
        return ""
    c = 0
    for i, item in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][int(item)]]
    return digits + str(_VERHOEFF_INV[c])


_MASKED_AADHAAR_PATTERN = re.compile(
    r"^(?:[Xx*•×]{4}[\s\-_]*[Xx*•×]{4}|[Xx*•×]{8})[\s\-_]*(\d{4})$"
)


def is_masked_aadhaar(aadhaar_str: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if an Aadhaar number is in UIDAI official masked format (e.g. 'XXXX XXXX 1107').
    Returns (is_masked, last4_digits).
    """
    if not aadhaar_str:
        return False, None
    clean = str(aadhaar_str).strip()
    m = _MASKED_AADHAAR_PATTERN.match(clean)
    if m:
        return True, m.group(1)
    m2 = re.search(r"(?:[Xx*•×]{4}[\s\-_]+[Xx*•×]{4}|[Xx*•×]{8})[\s\-_]+(\d{4})\b", clean)
    if m2:
        return True, m2.group(1)
    digits = re.sub(r"\D", "", clean)
    mask_chars = len(re.findall(r"[Xx*•×]", clean))
    if mask_chars >= 4 and len(digits) == 4:
        return True, digits
    return False, None


# ⚠️ Important caveat: not all real Aadhaar numbers are guaranteed to follow
# Verhoeff validation cleanly in every legacy case — treat a failed checksum
# as a risk signal to raise, not an automatic hard-reject. Surface it as
# aadhaar_checksum_valid: bool alongside other fields rather than blocking extraction.
def validate_aadhaar_number(aadhaar_str: str) -> Tuple[bool, Optional[bool], Optional[str]]:
    """
    Validates an Aadhaar number against UIDAI rules:
    - Official UIDAI masked format (e.g. 'XXXX XXXX 1107'): skips Verhoeff check with reason
      "masked Aadhaar — full number not printed; checksum not applicable".
    - 12 digits total (ignoring spaces/hyphens).
    - First digit cannot be 0 or 1.
    - Verhoeff checksum.

    Returns:
        (format_valid, checksum_valid, error_reason)
    """
    masked, last4 = is_masked_aadhaar(aadhaar_str)
    if masked:
        return (True, None, "masked Aadhaar — full number not printed; checksum not applicable")

    clean = re.sub(r"[\s\-]", "", str(aadhaar_str or ""))
    if len(clean) != 12 or not clean.isdigit():
        return (False, False, f"Aadhaar number must be exactly 12 digits, got {len(clean)}")

    if clean[0] in ("0", "1"):
        return (False, False, "Aadhaar first digit cannot be 0 or 1 per UIDAI rules")

    checksum_ok = validate_verhoeff(clean)
    if not checksum_ok:
        return (True, False, "Verhoeff checksum validation failed")

    return (True, True, None)


# ---------------------------------------------------------------------------
# Format Validators & Decoders
# ---------------------------------------------------------------------------

_PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_EPIC_REGEX = re.compile(r"^[A-Z]{3}[0-9]{7}$")

PAN_HOLDER_TYPES: dict[str, str] = {
    "P": "Individual",
    "C": "Company",
    "H": "HUF",
    "A": "AOP",
    "T": "Trust",
    "F": "Firm",
    "B": "BOI",
    "L": "Local Authority",
    "J": "Artificial Judicial Person",
    "G": "Government",
}


def validate_pan_format(pan_str: str) -> bool:
    """
    PAN number must be exactly 10 characters: 5 uppercase letters + 4 digits + 1 uppercase letter.
    Rejects lowercase, wrong length, or digits in letter positions.
    """
    clean = str(pan_str or "").strip()
    return bool(_PAN_REGEX.match(clean))


def decode_pan_details(pan_str: str) -> dict[str, Optional[str]]:
    """
    Extracts holder type and surname initial from a valid 10-char PAN string.
    Character 4 = Holder type (e.g. 'P' = Individual).
    Character 5 = Surname initial (for individuals).
    """
    clean = str(pan_str or "").strip()
    if not validate_pan_format(clean):
        return {
            "pan_format_valid": False,
            "pan_holder_type": None,
            "surname_initial": None,
        }

    holder_char = clean[3]
    holder_type = PAN_HOLDER_TYPES.get(holder_char, "Unknown")
    surname_initial = clean[4]

    return {
        "pan_format_valid": True,
        "pan_holder_type": holder_type,
        "surname_initial": surname_initial,
    }



def validate_epic_format(epic_str: str) -> bool:
    """
    Modern standard Voter ID (EPIC) must be exactly 3 uppercase letters + 7 digits (e.g. ABC1234567).
    """
    clean = str(epic_str or "").strip()
    return bool(_EPIC_REGEX.match(clean))

