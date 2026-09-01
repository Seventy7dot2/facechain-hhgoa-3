from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from facechain.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class ModelSpec:
    filename: str
    url: str
    sha256: str


MODELS = (
    ModelSpec(
        filename="face_detection_yunet_2026may.onnx",
        url=(
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "face_detection_yunet/face_detection_yunet_2026may.onnx"
        ),
        sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    ),
    ModelSpec(
        filename="face_recognition_sface_2021dec.onnx",
        url=(
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "face_recognition_sface/face_recognition_sface_2021dec.onnx"
        ),
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
)


def default_model_dir() -> Path:
    return Path.cwd() / "models"


def model_paths(model_dir: Path | None = None) -> tuple[Path, Path]:
    root = model_dir or default_model_dir()
    paths = tuple(root / spec.filename for spec in MODELS)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ConfigurationError(
            "face models are missing; run `facechain download-models` first (missing: "
            + ", ".join(missing)
            + ")"
        )
    invalid = [
        spec.filename
        for spec, path in zip(MODELS, paths, strict=True)
        if _digest(path.read_bytes()) != spec.sha256
    ]
    if invalid:
        raise ConfigurationError(
            "face model checksum verification failed; remove and re-download: " + ", ".join(invalid)
        )
    return paths[0], paths[1]


def download_models(model_dir: Path | None = None) -> list[Path]:
    root = model_dir or default_model_dir()
    root.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        for spec in MODELS:
            destination = root / spec.filename
            if destination.is_file() and _digest(destination.read_bytes()) == spec.sha256:
                downloaded.append(destination)
                continue
            try:
                response = client.get(spec.url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ConfigurationError(f"could not download {spec.filename}: {exc}") from exc
            if _digest(response.content) != spec.sha256:
                raise ConfigurationError(f"checksum verification failed for {spec.filename}")
            destination.write_bytes(response.content)
            downloaded.append(destination)
    return downloaded


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
