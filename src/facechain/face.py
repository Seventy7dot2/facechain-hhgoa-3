from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2 as cv
import numpy as np

from facechain.errors import FaceDetectionError

SFACE_COSINE_THRESHOLD = 0.363
MAX_SEARCH_UPLOAD_BYTES = 500_000


@dataclass(frozen=True, slots=True)
class FaceEncoding:
    image: np.ndarray
    feature: np.ndarray
    face_row: np.ndarray
    detected_faces: int


class FaceEngine:
    """OpenCV YuNet detector plus SFace encoder/matcher."""

    def __init__(self, detector_model: Path, recognizer_model: Path) -> None:
        self._detector = cv.FaceDetectorYN.create(
            str(detector_model), "", (320, 320), 0.9, 0.3, 5000
        )
        self._recognizer = cv.FaceRecognizerSF.create(str(recognizer_model), "")

    def encode_primary(self, image_bytes: bytes) -> FaceEncoding:
        image = decode_image(image_bytes)
        faces = self._detect(image)
        if faces is None or len(faces) == 0:
            raise FaceDetectionError("no face was detected in the image")
        primary = max(faces, key=lambda row: float(row[2] * row[3]))
        aligned = self._recognizer.alignCrop(image, primary)
        feature = self._recognizer.feature(aligned).copy()
        return FaceEncoding(image, feature, primary.copy(), len(faces))

    def best_similarity(self, target_feature: np.ndarray, image_bytes: bytes) -> tuple[float, int]:
        image = decode_image(image_bytes)
        faces = self._detect(image)
        if faces is None or len(faces) == 0:
            raise FaceDetectionError("no face was detected in the candidate image")
        scores: list[float] = []
        for face in faces:
            aligned = self._recognizer.alignCrop(image, face)
            feature = self._recognizer.feature(aligned)
            score = self._recognizer.match(target_feature, feature, cv.FaceRecognizerSF_FR_COSINE)
            scores.append(float(score))
        return max(scores), len(faces)

    def _detect(self, image: np.ndarray) -> np.ndarray | None:
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(image)
        return faces


def decode_image(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        raise FaceDetectionError("image is empty")
    image = cv.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv.IMREAD_COLOR)
    if image is None:
        raise FaceDetectionError("file is not a supported or valid image")
    return image


def prepare_search_crop(encoding: FaceEncoding) -> bytes:
    """Crop the primary face with context and encode it below SerpApi's 500 KB limit."""
    image = encoding.image
    x, y, width, height = (float(value) for value in encoding.face_row[:4])
    padding = 0.35
    x1 = max(0, int(x - width * padding))
    y1 = max(0, int(y - height * padding))
    x2 = min(image.shape[1], int(x + width * (1 + padding)))
    y2 = min(image.shape[0], int(y + height * (1 + padding)))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise FaceDetectionError("detected face produced an invalid search crop")

    largest_side = max(crop.shape[:2])
    if largest_side > 1200:
        scale = 1200 / largest_side
        crop = cv.resize(crop, None, fx=scale, fy=scale, interpolation=cv.INTER_AREA)

    for quality in (92, 85, 75, 65, 55):
        ok, encoded = cv.imencode(".jpg", crop, [cv.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(encoded) <= MAX_SEARCH_UPLOAD_BYTES:
            return encoded.tobytes()
    raise FaceDetectionError("face crop could not be compressed below the 500 KB search limit")
