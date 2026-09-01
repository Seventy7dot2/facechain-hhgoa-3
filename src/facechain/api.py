from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from facechain import __version__
from facechain.errors import FaceChainError
from facechain.pipeline import run_pipeline

MAX_UPLOAD_BYTES = 15_000_000
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _allowed_origins() -> list[str]:
    configured = os.getenv("FACECHAIN_ALLOWED_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


app = FastAPI(
    title="FaceChain Evidence API",
    description="Local API for face discovery and Ethereum evidence anchoring.",
    version=__version__,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ready", "version": __version__}


@app.post("/api/runs")
async def create_run(
    image: Annotated[UploadFile, File(description="A JPG, PNG, or WebP face image")],
    chain: Annotated[str, Form()] = "local",
) -> dict[str, Any]:
    if image.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, or WebP image.")
    if chain not in {"local", "sepolia"}:
        raise HTTPException(status_code=422, detail="Chain must be local or sepolia.")

    content = await image.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded image is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The image exceeds the 15 MB limit.")

    suffix = Path(image.filename or "face.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="facechain-upload-", suffix=suffix, delete=False
        ) as file:
            file.write(content)
            temporary_path = Path(file.name)
        evidence_path, bundle = await run_in_threadpool(
            run_pipeline,
            temporary_path,
            chain_backend=chain,
            artifact_root=Path(os.getenv("FACECHAIN_ARTIFACT_ROOT", "artifacts")),
        )
    except FaceChainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The pipeline failed unexpectedly.") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "status": "verified",
        "run_id": bundle["run_id"],
        "source_url": bundle["match"]["source_url"],
        "source_title": bundle["match"]["title"],
        "source_platform": bundle["match"]["source"],
        "cosine_similarity": bundle["match"]["cosine_similarity"],
        "content_sha256": bundle["match"]["content_sha256"],
        "identity": bundle["identity"],
        "social_profiles": bundle["social_profiles"],
        "blockchain": bundle["blockchain"],
        "evidence_path": str(evidence_path),
        "privacy": bundle["privacy"],
    }
