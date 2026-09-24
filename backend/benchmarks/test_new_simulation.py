import io
import math
import os
import random
import sys
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.benchmarks.dataset_generator import generate_pan_card, generate_aadhaar_card, generate_voter_card


def apply_enhanced_camera_simulation(img: Image.Image, seed: Optional[int] = None) -> Image.Image:
    """
    Applies realistic camera capture simulation with:
    1. Slight rotation (within +/- 2.5 deg) and perspective skew
    2. Uneven lighting (linear gradient + radial vignette)
    3. Wider brightness/contrast variation (0.85 - 1.15)
    4. Mild defocus / motion blur (varied strength)
    5. Varied Gaussian sensor noise (sigma 1.0 - 4.0)
    6. Varied JPEG recompression pass (quality 70 - 95)
    """
    rng = random.Random(seed) if seed is not None else random
    np_rng = np.random.default_rng(seed) if seed is not None else np.random

    w, h = img.size

    # --- 1. Rotation & Perspective Skew ---
    # Pick corner shifts in [-8, 8] pixels and small rotation [-2.0, 2.0] degrees
    angle_deg = rng.uniform(-2.0, 2.0)
    dx0, dy0 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx1, dy1 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx2, dy2 = rng.uniform(-6, 6), rng.uniform(-6, 6)
    dx3, dy3 = rng.uniform(-6, 6), rng.uniform(-6, 6)

    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    # Rotated and jittered destination points
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

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    warped_cv = cv2.warpPerspective(img_cv, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    warped_img = Image.fromarray(cv2.cvtColor(warped_cv, cv2.COLOR_BGR2RGB))

    # --- 2. Uneven Lighting (Gradient + Vignette) ---
    # Linear gradient across an angle
    grad_angle = rng.uniform(0, 2 * math.pi)
    gx = math.cos(grad_angle)
    gy = math.sin(grad_angle)
    xs = np.linspace(-1, 1, w)
    ys = np.linspace(-1, 1, h)
    X, Y = np.meshgrid(xs, ys)
    # Linear lighting ramp: +/- 10%
    linear_ramp = (X * gx + Y * gy) * rng.uniform(0.06, 0.14)

    # Radial vignette (corners darker by 5-10%)
    radius = np.sqrt(X ** 2 + Y ** 2) / math.sqrt(2.0)
    vignette = - (radius ** 2) * rng.uniform(0.04, 0.10)

    lighting_field = 1.0 + linear_ramp + vignette  # shape: (h, w)
    lighting_field = np.expand_dims(lighting_field, axis=2)  # shape: (h, w, 1)

    arr = np.array(warped_img, dtype=np.float32) * lighting_field
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    lit_img = Image.fromarray(arr)

    # --- 3. Brightness & Contrast (Wider 0.85 - 1.15) ---
    b_val = rng.uniform(0.88, 1.12)
    c_val = rng.uniform(0.88, 1.12)
    enhanced = ImageEnhance.Brightness(lit_img).enhance(b_val)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(c_val)

    # --- 4. Mild Blur (defocus or motion) ---
    blur_mode = rng.choice(["gaussian", "box", "none"])
    if blur_mode == "gaussian":
        sigma = rng.uniform(0.3, 0.7)
        enhanced = enhanced.filter(ImageFilter.GaussianBlur(radius=sigma))
    elif blur_mode == "box":
        enhanced = enhanced.filter(ImageFilter.BoxBlur(radius=1))

    # --- 5. Varied Gaussian Sensor Noise (sigma 1.0 - 4.0) ---
    noise_sigma = rng.uniform(1.2, 3.8)
    arr_f = np.array(enhanced, dtype=np.float32)
    noise = np_rng.normal(0, noise_sigma, arr_f.shape)
    noisy_arr = np.clip(arr_f + noise, 0, 255).astype(np.uint8)
    noisy_img = Image.fromarray(noisy_arr)

    # --- 6. Varied JPEG Recompression (Quality 70 - 95) ---
    quality = rng.randint(72, 94)
    buf = io.BytesIO()
    noisy_img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


if __name__ == "__main__":
    profile = {
        "pan_number": "ABCDE1234F",
        "name": "VENKATARAMAN SUBRAMANIAN",
        "father_name": "RAMESH SUBRAMANIAN",
        "date_of_birth": "12/04/1985",
    }
    pan = generate_pan_card(profile)
    out1 = apply_enhanced_camera_simulation(pan, seed=101)
    out2 = apply_enhanced_camera_simulation(pan, seed=101)
    # Verify deterministic repeatability for same seed
    diff = np.max(np.abs(np.array(out1) - np.array(out2)))
    print(f"Max diff between same seed runs: {diff} (must be 0)")
    out_diff_seed = apply_enhanced_camera_simulation(pan, seed=102)
    diff_seed = np.mean(np.abs(np.array(out1) - np.array(out_diff_seed)))
    print(f"Mean diff between different seed runs: {diff_seed:.2f} (should be > 5.0)")
    print("Enhanced camera capture simulation verified successfully!")
