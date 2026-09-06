from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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
    request: Request,
    image: Annotated[UploadFile, File(description="A JPG, PNG, or WebP face image")],
    chain: Annotated[str, Form()] = "local",
) -> Any:
    if image.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, or WebP image.")
    if chain not in {"local", "sepolia"}:
        raise HTTPException(status_code=422, detail="Chain must be local or sepolia.")

    content = await image.read(MAX_UPLOAD_BYTES + 1)
    await image.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded image is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The image exceeds the 15 MB limit.")

    suffix = Path(image.filename or "face.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    temporary_path = _write_temporary_upload(content, suffix)
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            _stream_run(temporary_path, chain),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
        )

    try:
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
        temporary_path.unlink(missing_ok=True)

    return _frontend_result(evidence_path, bundle)


def _write_temporary_upload(content: bytes, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix="facechain-upload-", suffix=suffix, delete=False
    ) as file:
        file.write(content)
        return Path(file.name)


def _frontend_result(evidence_path: Path, bundle: dict[str, Any]) -> dict[str, Any]:
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


def _stream_run(temporary_path: Path, chain: str):
    events: Queue[dict[str, Any] | None] = Queue()

    def execute() -> None:
        last_event: dict[str, Any] = {}

        def emit(event: dict[str, Any]) -> None:
            last_event.clear()
            last_event.update(event)
            events.put(event)

        try:
            evidence_path, bundle = run_pipeline(
                temporary_path,
                chain_backend=chain,
                artifact_root=Path(os.getenv("FACECHAIN_ARTIFACT_ROOT", "artifacts")),
                progress=emit,
            )
            events.put(
                {
                    "id": "result",
                    "run_id": bundle["run_id"],
                    "stage": "verify",
                    "state": "finished",
                    "message": "Discovery, face confirmation, and evidence verification completed",
                    "elapsed_ms": last_event.get("elapsed_ms"),
                    "duration_ms": last_event.get("duration_ms"),
                    "data": {"result": _frontend_result(evidence_path, bundle)},
                }
            )
        except FaceChainError as exc:
            events.put(
                {
                    "id": "error",
                    "run_id": last_event.get("run_id"),
                    "stage": last_event.get("stage", "pipeline"),
                    "state": "failed",
                    "message": str(exc),
                    "elapsed_ms": last_event.get("elapsed_ms"),
                    "duration_ms": last_event.get("duration_ms"),
                    "data": {},
                }
            )
        except Exception:
            events.put(
                {
                    "id": "error",
                    "run_id": last_event.get("run_id"),
                    "stage": last_event.get("stage", "pipeline"),
                    "state": "failed",
                    "message": "The pipeline failed unexpectedly. Check the server logs.",
                    "elapsed_ms": last_event.get("elapsed_ms"),
                    "duration_ms": last_event.get("duration_ms"),
                    "data": {},
                }
            )
        finally:
            temporary_path.unlink(missing_ok=True)
            events.put(None)

    worker = Thread(target=execute, name="facechain-stream", daemon=True)
    worker.start()
    while (event := events.get()) is not None:
        yield f"event: progress\ndata: {json.dumps(event)}\n\n"
    worker.join()
