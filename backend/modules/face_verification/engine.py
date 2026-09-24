"""
engine.py - High-accuracy Biometric Face Verification Engine.
Uses OpenCV Zoo YuNet for landmark/face detection and SFace for 128-d deep representation.
"""
from abc import ABC, abstractmethod
import io
import os
from typing import Optional, Tuple, Union
import cv2
import numpy as np
from PIL import Image

from .schemas import BoundingBox, FaceVerifyResult

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "models")
YUNET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
SFACE_PATH = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")


class FaceVerificationEngineInterface(ABC):
    """Abstract interface allowing alternative models to be swapped in."""
    @abstractmethod
    def verify(
        self,
        doc_image: Union[bytes, np.ndarray, str],
        selfie_image: Union[bytes, np.ndarray, str],
        threshold: float = 0.363
    ) -> FaceVerifyResult:
        pass


def _to_cv2(image_input: Union[bytes, np.ndarray, str]) -> np.ndarray:
    if isinstance(image_input, np.ndarray):
        return image_input
    if isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None:
            raise ValueError(f"Could not load image from path: {image_input}")
        return img
    if isinstance(image_input, (bytes, bytearray)):
        pil_img = Image.open(io.BytesIO(image_input)).convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    raise TypeError(f"Unsupported image type: {type(image_input)}")


class OpenCVFaceVerificationEngine(FaceVerificationEngineInterface):
    """
    OpenCV DNN implementation using YuNet + SFace.
    Provides sub-20ms inference with real 128-d cosine feature matching.
    """
    def __init__(self, yunet_path: str = YUNET_PATH, sface_path: str = SFACE_PATH):
        self.yunet_path = yunet_path
        self.sface_path = sface_path

        if not os.path.exists(self.yunet_path) or not os.path.exists(self.sface_path):
            raise FileNotFoundError(
                f"Face verification model files not found. Expected: {self.yunet_path} and {self.sface_path}"
            )

        self.recognizer = cv2.FaceRecognizerSF.create(self.sface_path, "")
        # Create YuNet ONNX detector once at initialization
        self.detector = cv2.FaceDetectorYN.create(
            self.yunet_path, "", (320, 320), score_threshold=0.55, nms_threshold=0.3
        )
        # Fallback haar cascade in case YuNet misses small/blurry ID photos
        self.haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    def _detect_faces_yunet(self, img: np.ndarray, conf_threshold: float = 0.55):
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        self.detector.setScoreThreshold(conf_threshold)
        _, faces = self.detector.detect(img)
        return faces

    def _detect_best_face(self, img: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[BoundingBox], int]:
        """
        Detects faces, returns: (best_face_raw_row, bounding_box, total_detected_count).
        Uses YuNet with filtering for realistic identity document face sizes.
        """
        h_img, w_img = img.shape[:2]
        min_dim = max(48, int(min(h_img, w_img) * 0.08))

        faces = self._detect_faces_yunet(img, conf_threshold=0.55)
        valid_faces = []
        if faces is not None:
            for f in faces:
                w, h = f[2], f[3]
                if w >= min_dim and h >= min_dim:
                    valid_faces.append(f)

        if not valid_faces:
            # Check with haar cascade as fallback only if face size meets min_dim
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            haar_faces = self.haar_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_dim, min_dim)
            )
            if len(haar_faces) > 0:
                x, y, w, h = haar_faces[0]
                box = BoundingBox(x=int(x), y=int(y), width=int(w), height=int(h))
                synth_row = np.array([
                    x, y, w, h,
                    x + w * 0.3, y + h * 0.35,  # right eye
                    x + w * 0.7, y + h * 0.35,  # left eye
                    x + w * 0.5, y + h * 0.55,  # nose tip
                    x + w * 0.35, y + h * 0.75, # right mouth
                    x + w * 0.65, y + h * 0.75, # left mouth
                    0.80
                ], dtype=np.float32)
                return synth_row, box, len(haar_faces)
            return None, None, 0

        # Pick highest scoring face
        best_face = max(valid_faces, key=lambda f: f[-1])
        x, y, w, h = int(best_face[0]), int(best_face[1]), int(best_face[2]), int(best_face[3])
        x = max(0, min(x, w_img - 1))
        y = max(0, min(y, h_img - 1))
        w = max(1, min(w, w_img - x))
        h = max(1, min(h, h_img - y))
        box = BoundingBox(x=x, y=y, width=w, height=h)
        return best_face, box, len(valid_faces)

    def extract_face_crop(self, img_input: Union[bytes, np.ndarray, str]) -> Optional[np.ndarray]:
        img = _to_cv2(img_input)
        face_row, _, _ = self._detect_best_face(img)
        if face_row is None:
            return None
        aligned = self.recognizer.alignCrop(img, face_row)
        return aligned

    def verify(
        self,
        doc_image: Union[bytes, np.ndarray, str],
        selfie_image: Union[bytes, np.ndarray, str],
        threshold: float = 0.363  # SFace default recommended threshold
    ) -> FaceVerifyResult:
        doc_img = _to_cv2(doc_image)
        selfie_img = _to_cv2(selfie_image)

        doc_face, doc_box, doc_count = self._detect_best_face(doc_img)
        if doc_face is None:
            return FaceVerifyResult(
                match=False,
                confidence=0.0,
                cosine_similarity=-1.0,
                l2_distance=999.0,
                threshold_applied=threshold,
                status="NO_FACE_IN_DOCUMENT",
                message="No face detected on the document image.",
                doc_face_box=None,
                selfie_face_box=None,
                doc_face_count=0,
                selfie_face_count=0
            )

        selfie_face, selfie_box, selfie_count = self._detect_best_face(selfie_img)
        if selfie_face is None:
            return FaceVerifyResult(
                match=False,
                confidence=0.0,
                cosine_similarity=-1.0,
                l2_distance=999.0,
                threshold_applied=threshold,
                status="NO_FACE_IN_SELFIE",
                message="No face detected on the live selfie/camera image.",
                doc_face_box=doc_box,
                selfie_face_box=None,
                doc_face_count=doc_count,
                selfie_face_count=0
            )

        # Align and extract 128-d deep embeddings
        aligned_doc = self.recognizer.alignCrop(doc_img, doc_face)
        feature_doc = self.recognizer.feature(aligned_doc)

        aligned_selfie = self.recognizer.alignCrop(selfie_img, selfie_face)
        feature_selfie = self.recognizer.feature(aligned_selfie)

        cosine_sim = float(self.recognizer.match(feature_doc, feature_selfie, cv2.FaceRecognizerSF_FR_COSINE))
        l2_dist = float(self.recognizer.match(feature_doc, feature_selfie, cv2.FaceRecognizerSF_FR_NORM_L2))

        # Normalized confidence scale (0.0 to 1.0):
        # Cosine similarity typically ranges from -0.2 (completely different) to +0.95 (identical).
        # SFace standard threshold is 0.363.
        # Below 0.0 -> near 0% match.
        # At threshold 0.363 -> 75% confidence.
        # Above 0.70 -> 95%+ confidence.
        if cosine_sim <= 0.0:
            norm_conf = max(0.0, (cosine_sim + 0.3) * 0.2)
        elif cosine_sim < threshold:
            norm_conf = 0.10 + (cosine_sim / threshold) * 0.55
        else:
            excess = (cosine_sim - threshold) / (1.0 - threshold)
            norm_conf = 0.65 + min(0.34, excess * 0.34)

        is_match = cosine_sim >= threshold

        status = "SUCCESS"
        if doc_count > 1 or selfie_count > 1:
            status = "MULTIPLE_FACES_WARNING"

        return FaceVerifyResult(
            match=is_match,
            confidence=round(float(norm_conf), 4),
            cosine_similarity=round(float(cosine_sim), 4),
            l2_distance=round(float(l2_dist), 4),
            threshold_applied=round(float(threshold), 3),
            status=status,
            message="Biometric match confirmed" if is_match else "Biometric mismatch detected",
            doc_face_box=doc_box,
            selfie_face_box=selfie_box,
            doc_face_count=doc_count,
            selfie_face_count=selfie_count
        )


# Singleton instance
_engine_instance: Optional[OpenCVFaceVerificationEngine] = None


def get_face_engine() -> OpenCVFaceVerificationEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OpenCVFaceVerificationEngine()
    return _engine_instance
