"""
test_face_verify.py - Unit tests for Biometric Face Verification (Module 4).
"""
import pytest
from backend.modules.face_verification.engine import get_face_engine


def test_face_engine_loaded():
    engine = get_face_engine()
    assert engine is not None
    assert engine.recognizer is not None


def test_face_verification_same_vs_diff_photos():
    engine = get_face_engine()
    p_thada_front = r"public/samples/aadhaar_thada_front.png"
    p_thada_merged = r"public/samples/aadhaar_thada_merged.png"
    p_srija = r"public/samples/aadhaar_srija.png"

    # Same person comparison
    res_same = engine.verify(p_thada_front, p_thada_merged)
    assert res_same.match is True
    assert res_same.confidence > 0.80
    assert res_same.cosine_similarity > 0.50

    # Different person comparison
    res_diff = engine.verify(p_thada_front, p_srija)
    assert res_diff.match is False
    assert res_diff.cosine_similarity < 0.363


def test_face_verification_no_face_handling():
    engine = get_face_engine()
    p_doc = r"public/samples/aadhaar_thada_front.png"
    p_back = r"public/samples/aadhaar_thada_back.jpg"  # Back has no portrait

    res = engine.verify(p_doc, p_back)
    assert res.match is False
    assert res.status == "NO_FACE_IN_SELFIE"
