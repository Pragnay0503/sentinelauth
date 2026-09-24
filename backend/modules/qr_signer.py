"""
qr_signer.py - Cryptographic Signing & Verification for Simulated Aadhaar Secure QR.

NOTE: This simulates UIDAI's digitally signed 2048-bit RSA QR code for testing purposes.
It uses an internal, clearly-labeled test key pair. It does NOT use or mimic real UIDAI private keys.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import serialization

_TEST_PRIV_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCu7FrAFynriwU3
BtCchGvWX/5AtUQzEcT+nO2MFljTvXEDaiMdNa3KKO+6LyWVSUfiyMbxpZrAT075
ky4oOw6BtjzUUoZE/QdQ+UYY58n+ZyXsTKl2A9Aln6aQ35Uu7BK2uq+r4hpKaFcy
apbuMtKyLIWIIaehjhJIHeits5t0Qo44ldChPJhm9OARMicrDHQPMHyqXHtTgYO8
KP0GMR+mIRl5W1RVMqiqYbRVoC6vu9M8lLCqKL7A9EnRH4s51EwxSyjSkKWFMoQ8
gnWAMENR56PXpa6NdDVmgQXAdFf9k2ptevmNC/mwjHGj9TMdktEMbtjlVdc+xDu+
Q+g++3RrAgMBAAECggEAFLUkP83o3NqAoTVW/YBrp7LbeDDn7vJxPgG5LraiiLEf
hNuhZol+ll+8PsVAD2k1Gl18Yl+hb0IJmQqvEdIpSHpuFGXklpwsVo3772Iui8W4
O+i4vaDRQ52fwVIb6LRyZAa7rym9b7DkdF0hRaI8m8fLfa8bl3N91I293XpVXTDP
/S2KDI3UfM9MH621Vswadt6W/f4bgHOvsAiwKBTKQ/bFekTRNsYhidqIP8HZW4C7
4Oq8fJEBZG1+ouL4zpIrX1MwysIY+Q5ew51Lf4arNnkaF+fg+3X+GRAwv44aV6m7
B9UbAAQ7rl06T30oTub7whBCpw9bjTfpklTQ4uiwUQKBgQDwsoDa+nYv10nq+d2I
Fc8BYsm5di64cU0ZRToBZ1CkzaX5VT0xPr0MWkmL84WFs3x/vnRNUUMhzkIlba+k
VFAFzY4+l+7ANfkyfkj2e0dd5LCvsLMfBcb6eTYlEH6adl0sQneOayNnTQNcg3lJ
RcHvtKZWbbU0apYYI34cmkocqQKBgQC6C1ajPpNAReTkE5uCSDdpcjzATYn7YKzZ
eZgHtH3Ufreum91Crdv3oF+Jkjig3hXWK+OmUhr4YPmOWbocXc0+Y1hsxufFEQkg
wR2IfsLnTYFgMb/WWhNyXuQQ4c0MNhIFwgj9Td0OECI1lUQlA+l5W4WzVgDg40Q1
uQdlmrhA8wKBgBaev+tUZG0Ej4bMqpwSaJzZutl6GNPume9JCTV+jx6d0P5Im3KY
Uc3qYkULwr2Y65dZv7ZQb72qk57O2xXXcpnJApgxURexOtUa9yJq3X8ecdhhA8Rj
l5qMb6E2Fp/PhdwV9wRkXzRjEXDNTkWrj5lGYed3cfMWHTrxgvWPLm3ZAoGAFBqp
kBZw/x8Obv8XbOq04jYwDm/Sm1GFHDMhlKOSfWX8H2hEbrIu9QFlkY41hFy7a1tu
zEhPFcwU66cSj4IrbbR6l7ae0RLYM6vqrxdTpH8hne2CV32AYHmUl6Zu7ATjya+A
HS9O1fg0Win5JS7ZCf4z4n9GtQaaFlwaSoZ/prUCgYEAmpzmUf3zKuaMSsXhHlV1
ArOeoaIlmt74wA5Ua5Y00XZnster4XvSrlkrghsT0ldSdlsI4Io7i0XBUdPhnHMX
uvIy1tgiY8TR9dnLrF82b0F8ZsqdTdhsSQMYvmMnPaggH9KAFbhN6bngwE1Ij3AW
Uw6MOB13PMMSpVrdZ9cSvuk=
-----END PRIVATE KEY-----
"""
_TEST_PUB_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAruxawBcp64sFNwbQnIRr
1l/+QLVEMxHE/pztjBZY071xA2ojHTWtyijvui8llUlH4sjG8aWawE9O+ZMuKDsO
gbY81FKGRP0HUPlGGOfJ/mcl7EypdgPQJZ+mkN+VLuwStrqvq+IaSmhXMmqW7jLS
siyFiCGnoY4SSB3orbObdEKOOJXQoTyYZvTgETInKwx0DzB8qlx7U4GDvCj9BjEf
piEZeVtUVTKoqmG0VaAur7vTPJSwqii+wPRJ0R+LOdRMMUso0pClhTKEPIJ1gDBD
Ueej16WujXQ1ZoEFwHRX/ZNqbXr5jQv5sIxxo/UzHZLRDG7Y5VXXPsQ7vkPoPvt0
awIDAQAB
-----END PUBLIC KEY-----
"""

_TEST_PRIVATE_KEY = serialization.load_pem_private_key(
    _TEST_PRIV_PEM.encode("ascii"),
    password=None,
)
_TEST_PUBLIC_KEY = serialization.load_pem_public_key(
    _TEST_PUB_PEM.encode("ascii"),
)


def generate_signed_qr_payload(data: Dict[str, Any]) -> str:
    """
    Serializes demographic data and produces a cryptographically signed QR text.
    Payload format: UIDAI_SIM:<base64_json_payload>.<base64_sha256_rsa_signature>
    """
    json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(json_bytes).decode("ascii")

    signature = _TEST_PRIVATE_KEY.sign(
        json_bytes,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    sig_b64 = base64.urlsafe_b64encode(signature).decode("ascii")
    return f"UIDAI_SIM:{payload_b64}.{sig_b64}"


def verify_signed_qr_payload(qr_text: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verifies the simulated UIDAI RSA signature on the QR text.
    Returns:
        (is_valid, decoded_data_dict, explanation)
    """
    if not qr_text:
        return False, None, "Empty QR data"

    if not qr_text.startswith("UIDAI_SIM:"):
        return False, None, "Missing UIDAI_SIM signature envelope prefix"

    body = qr_text[len("UIDAI_SIM:"):]
    parts = body.split(".")
    if len(parts) != 2:
        return False, None, "Malformed QR payload structure (expected payload.signature)"

    payload_b64, sig_b64 = parts[0], parts[1]
    try:
        json_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        sig_bytes = base64.urlsafe_b64decode(sig_b64.encode("ascii"))
    except Exception as e:
        return False, None, f"Base64 decoding failed: {e}"

    # Verify signature
    try:
        _TEST_PUBLIC_KEY.verify(
            sig_bytes,
            json_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        data = json.loads(json_bytes.decode("utf-8"))
        return True, data, "Valid RSA signature from authorized issuer test key"
    except Exception:
        try:
            tampered_data = json.loads(json_bytes.decode("utf-8"))
        except Exception:
            tampered_data = None
        return False, tampered_data, "Cryptographic RSA signature verification failed (tampered QR or unauthorized issuer)"
