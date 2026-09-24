"""
calibrate_morph_detection.py - Verification & Threshold Calibration for Module 4 Face-Morphing Attack Detection.

Generates synthetic face morphs using Delaunay/affine landmark warping and evaluates
genuine vs morphed document photos to report:
  1. Genuine False-Positive Rate (FPR)
  2. Synthetic Morph True-Positive Detection Rate (TPR)
  3. Signal-by-signal score breakdown
"""
import os
import sys
import cv2
import numpy as np

sys.path.insert(0, os.path.abspath('.'))
from backend.modules.face_verification.morph_detection import detect_morphing, YUNET_PATH

def create_synthetic_morph(img1_path: str, img2_path: str, output_path: str) -> bool:
    """Creates a verified synthetic face morph by blending donor 1 and donor 2 at 50/50 geometry."""
    img1 = cv2.imread(img1_path)
    img2 = cv2.imread(img2_path)
    if img1 is None or img2 is None:
        return False
        
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    
    det1 = cv2.FaceDetectorYN.create(YUNET_PATH, '', (w1, h1), score_threshold=0.5)
    det2 = cv2.FaceDetectorYN.create(YUNET_PATH, '', (w2, h2), score_threshold=0.5)
    
    _, faces1 = det1.detect(img1)
    _, faces2 = det2.detect(img2)
    if faces1 is None or faces2 is None:
        return False
        
    # Pick largest face by bounding box area (main identity portrait)
    f1 = max(faces1, key=lambda f: f[2] * f[3])
    f2 = max(faces2, key=lambda f: f[2] * f[3])
    
    pts1 = np.array([[f1[4], f1[5]], [f1[6], f1[7]], [f1[8], f1[9]], [f1[10], f1[11]], [f1[12], f1[13]]], dtype=np.float32)
    pts2 = np.array([[f2[4], f2[5]], [f2[6], f2[7]], [f2[8], f2[9]], [f2[10], f2[11]], [f2[12], f2[13]]], dtype=np.float32)
    
    # 50/50 morph landmarks
    pts_morph = 0.5 * pts1 + 0.5 * pts2
    
    warp1, _ = cv2.estimateAffinePartial2D(pts1, pts_morph)
    warp2, _ = cv2.estimateAffinePartial2D(pts2, pts_morph)
    
    warped1 = cv2.warpAffine(img1, warp1, (w1, h1), borderMode=cv2.BORDER_REFLECT)
    warped2 = cv2.warpAffine(img2, warp2, (w1, h1), borderMode=cv2.BORDER_REFLECT)
    
    blended = cv2.addWeighted(warped1, 0.5, warped2, 0.5, 0.0)
    
    # Feathered ellipse mask around morphed face
    cx = int((pts_morph[0, 0] + pts_morph[1, 0]) / 2.0)
    cy = int((pts_morph[0, 1] + pts_morph[3, 1]) / 2.0)
    mask = np.zeros((h1, w1), dtype=np.float32)
    cv2.ellipse(mask, (cx, cy), (int(f1[2] * 0.50), int(f1[3] * 0.58)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (21, 21), 0)[:, :, np.newaxis]
    
    morphed = (blended.astype(np.float32) * mask + img1.astype(np.float32) * (1.0 - mask)).astype(np.uint8)
    cv2.imwrite(output_path, morphed)
    return True

def run_calibration():
    samples_dir = os.path.join('public', 'samples')
    p_thada = os.path.join(samples_dir, 'aadhaar_thada_front.png')
    p_kaja = os.path.join(samples_dir, 'pan_kaja.png')
    p_srija = os.path.join(samples_dir, 'aadhaar_srija.png')
    
    m1_path = os.path.join(samples_dir, 'synthetic_morph_thada_kaja.png')
    m2_path = os.path.join(samples_dir, 'synthetic_morph_srija_kaja.png')
    
    create_synthetic_morph(p_thada, p_kaja, m1_path)
    create_synthetic_morph(p_srija, p_kaja, m2_path)
    
    genuine_cases = [
        ("Aadhaar Thada (Front)", p_thada),
        ("PAN Kaja", p_kaja),
        ("Aadhaar Srija", p_srija)
    ]
    
    morphed_cases = [
        ("Synthetic Morph (Thada + Kaja)", m1_path),
        ("Synthetic Morph (Srija + Kaja)", m2_path)
    ]
    
    print("=" * 80)
    print("MODULE 4 EXTENSION: FACE-MORPHING ATTACK DETECTION (S-MAD) CALIBRATION REPORT")
    print("=" * 80)
    
    # 1. Test Genuine Baselines
    print("\n[1] GENUINE BASELINE EVALUATION (Target: 0 False Positives)")
    print("-" * 80)
    fp_count = 0
    for name, path in genuine_cases:
        with open(path, 'rb') as f:
            b = f.read()
        res = detect_morphing(b)
        is_fp = res.is_morph_suspected
        if is_fp:
            fp_count += 1
        status = "FALSE POSITIVE" if is_fp else "VERIFIED AUTHENTIC (PASS)"
        print(f"  • {name:<32} | Score: {res.morph_suspicion_score:.3f} | Tier: {res.suspicion_tier:<14} | {status}")
        for sig_name, sig in res.signals.items():
            print(f"      - {sig_name:<26}: score={sig.score:.3f}, flagged={sig.flagged}")
            
    genuine_fpr = (fp_count / len(genuine_cases)) * 100.0
    print(f"\n  --> Genuine False-Positive Rate (FPR): {genuine_fpr:.1f}% ({fp_count}/{len(genuine_cases)})")
    
    # 2. Test Synthetic Morphs
    print("\n[2] SYNTHETIC MORPH ATTACK DETECTION EVALUATION (Target: High Detection Rate)")
    print("-" * 80)
    tp_count = 0
    for name, path in morphed_cases:
        with open(path, 'rb') as f:
            b = f.read()
        res = detect_morphing(b)
        is_tp = res.is_morph_suspected
        if is_tp:
            tp_count += 1
        status = "DETECTED (TRUE POSITIVE)" if is_tp else "MISSED (FALSE NEGATIVE)"
        print(f"  • {name:<32} | Score: {res.morph_suspicion_score:.3f} | Tier: {res.suspicion_tier:<14} | {status}")
        print(f"      Flags: {res.morph_flags}")
        for sig_name, sig in res.signals.items():
            print(f"      - {sig_name:<26}: score={sig.score:.3f}, flagged={sig.flagged}")
            
    morph_tpr = (tp_count / len(morphed_cases)) * 100.0
    print(f"\n  --> Synthetic Morph Detection Rate (TPR): {morph_tpr:.1f}% ({tp_count}/{len(morphed_cases)})")
    print("=" * 80)

if __name__ == '__main__':
    run_calibration()
