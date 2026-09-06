from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import cv2 as cv
import numpy as np

from facechain.canonical import SCHEMA, canonical_json, make_chain_record, sha256_bytes
from facechain.chain import EthereumEvidenceChain
from facechain.errors import FaceDetectionError, NoMatchError, SearchError
from facechain.face import SFACE_COSINE_THRESHOLD, FaceEngine, prepare_search_crop
from facechain.model_store import model_paths
from facechain.models import ConfirmedMatch
from facechain.search import SerpApiLens

ProgressCallback = Callable[[dict[str, Any]], None]


class _Progress:
    def __init__(self, callback: ProgressCallback | None, run_id: str) -> None:
        self.callback = callback
        self.run_id = run_id
        self.started = monotonic()
        self.stage_started = self.started
        self.sequence = 0

    @property
    def enabled(self) -> bool:
        return self.callback is not None

    def start(self, stage: str, message: str, **data: Any) -> None:
        self.stage_started = monotonic()
        self._send(stage, "running", message, data)

    def update(self, stage: str, message: str, **data: Any) -> None:
        self._send(stage, "running", message, data)

    def complete(self, stage: str, message: str, **data: Any) -> None:
        self._send(stage, "completed", message, data)

    def _send(self, stage: str, state: str, message: str, data: dict[str, Any]) -> None:
        if self.callback is None:
            return
        self.sequence += 1
        self.callback(
            {
                "id": self.sequence,
                "run_id": self.run_id,
                "stage": stage,
                "state": state,
                "message": message,
                "elapsed_ms": round((monotonic() - self.started) * 1000, 3),
                "duration_ms": round((monotonic() - self.stage_started) * 1000, 3),
                "data": data,
            }
        )


def run_pipeline(
    image_path: Path,
    *,
    chain_backend: str = "local",
    artifact_root: Path = Path("artifacts"),
    model_dir: Path | None = None,
    max_candidates: int = 20,
    similarity_threshold: float = SFACE_COSINE_THRESHOLD,
    progress: ProgressCallback | None = None,
) -> tuple[Path, dict[str, Any]]:
    if not image_path.is_file():
        raise FaceDetectionError(f"input image does not exist: {image_path}")
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key.strip():
        raise SearchError("SERPAPI_KEY is required for a genuine live search")
    observed_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    live = _Progress(progress, run_id)
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    live.start("input", "Loading verified OpenCV models and encoding the primary face")
    detector_model, recognizer_model = model_paths(model_dir)
    face_engine = FaceEngine(detector_model, recognizer_model)
    input_bytes = image_path.read_bytes()
    input_face = face_engine.encode_primary(input_bytes)
    x, y, width, height = (round(float(value), 2) for value in input_face.face_row[:4])
    annotated_preview = ""
    if live.enabled:
        annotated = input_face.image.copy()
        cv.rectangle(
            annotated,
            (max(0, int(x)), max(0, int(y))),
            (int(x + width), int(y + height)),
            (1, 225, 254),
            max(2, round(max(annotated.shape[:2]) / 320)),
        )
        annotated_preview = _pixel_preview(annotated)
    live.complete(
        "input",
        "YuNet detected the input face and SFace created an in-memory feature vector",
        detected_faces=input_face.detected_faces,
        selected_face={"x": x, "y": y, "width": width, "height": height},
        image_width=int(input_face.image.shape[1]),
        image_height=int(input_face.image.shape[0]),
        embedding_dimensions=int(input_face.feature.size),
        preview=annotated_preview,
    )

    live.start("crop", "Cropping the primary face with context for reverse-image search")
    search_crop = prepare_search_crop(input_face)
    live.complete(
        "crop",
        "Search crop encoded below the SerpApi upload limit",
        preview=_data_url(search_crop, "image/jpeg") if live.enabled else "",
        bytes=len(search_crop),
        maximum_bytes=500_000,
    )

    with SerpApiLens(api_key) as search:
        live.start("search", "Uploading the real crop and waiting for Google Lens results")
        candidates, raw_search = search.search(search_crop)
        _write_json(run_dir / "search-response.json", raw_search)
        live.complete(
            "search",
            f"Google Lens returned {len(candidates)} supported social candidates",
            candidate_count=len(candidates),
            candidates=[
                {
                    "rank": candidate.rank,
                    "title": candidate.title,
                    "source": candidate.source,
                    "source_url": candidate.source_url,
                    "image_url": candidate.image_url,
                    "thumbnail_url": candidate.thumbnail_url,
                    "exact_match": candidate.exact_match,
                }
                for candidate in candidates[:max_candidates]
            ],
        )

        live.start("profiles", "Resolving identity evidence and associated social profiles")
        try:
            identity, social_profiles, profile_response = search.discover_social_profiles(
                raw_search
            )
        except SearchError as exc:
            identity, social_profiles = None, []
            profile_response = {"error": str(exc)}
        _write_json(run_dir / "profile-search-response.json", profile_response)
        live.complete(
            "profiles",
            f"Profile resolution retained {len(social_profiles)} evidence-backed profiles",
            identity=identity,
            profiles=[profile.to_dict() for profile in social_profiles],
        )
        if not candidates:
            raise NoMatchError("Google Lens returned no supported social-media results")

        confirmed: list[ConfirmedMatch] = []
        failures: list[dict[str, Any]] = []
        ranked = sorted(candidates, key=lambda item: (not item.exact_match, item.rank))
        inspected = ranked[:max_candidates]
        live.start(
            "confirm",
            f"Comparing up to {len(inspected)} candidate images with the input SFace vector",
            candidate_count=len(inspected),
            threshold=similarity_threshold,
        )
        for index, candidate in enumerate(inspected, start=1):
            live.update(
                "confirm",
                f"Downloading candidate {index} of {len(inspected)} from {candidate.source}",
                index=index,
                candidate_count=len(inspected),
                candidate=candidate.to_dict(),
            )
            try:
                candidate_bytes, media_type = search.download_candidate(candidate)
                score, face_count = face_engine.best_similarity(input_face.feature, candidate_bytes)
                accepted = score >= similarity_threshold
                live.update(
                    "confirm",
                    f"Candidate {index} scored {score:.4f} and was "
                    + ("accepted" if accepted else "rejected"),
                    index=index,
                    candidate_count=len(inspected),
                    candidate=candidate.to_dict(),
                    cosine_similarity=round(score, 6),
                    threshold=similarity_threshold,
                    accepted=accepted,
                    detected_faces=face_count,
                    preview=_image_preview(candidate_bytes) if live.enabled else "",
                )
                if score >= similarity_threshold:
                    confirmed.append(
                        ConfirmedMatch(
                            candidate=candidate,
                            cosine_similarity=score,
                            image_bytes=candidate_bytes,
                            image_media_type=media_type,
                            detected_faces=face_count,
                        )
                    )
                else:
                    failures.append(
                        {
                            "source_url": candidate.source_url,
                            "reason": "face similarity below threshold",
                            "cosine_similarity": round(score, 6),
                        }
                    )
            except (SearchError, FaceDetectionError) as exc:
                failures.append({"source_url": candidate.source_url, "reason": str(exc)})
                live.update(
                    "confirm",
                    f"Candidate {index} could not be confirmed and was skipped",
                    index=index,
                    candidate_count=len(inspected),
                    candidate=candidate.to_dict(),
                    accepted=False,
                    reason=str(exc),
                )

    _write_json(run_dir / "candidate-diagnostics.json", failures)
    if not confirmed:
        raise NoMatchError(
            f"no social result passed SFace confirmation at threshold {similarity_threshold}"
        )

    match = max(confirmed, key=lambda item: item.cosine_similarity)
    live.complete(
        "confirm",
        "The highest-scoring confirmed candidate was selected",
        confirmed_count=len(confirmed),
        rejected_count=len(failures),
        match={
            **match.candidate.to_dict(),
            "cosine_similarity": round(match.cosine_similarity, 6),
            "detected_faces": match.detected_faces,
            "preview": _image_preview(match.image_bytes) if live.enabled else "",
        },
    )

    live.start("evidence", "Hashing the exact matched bytes and canonical discovery metadata")
    image_suffix = _media_suffix(match.image_media_type)
    matched_image_name = "matched-content" + image_suffix
    (run_dir / matched_image_name).write_bytes(match.image_bytes)
    content_sha256 = sha256_bytes(match.image_bytes)

    search_id = raw_search.get("search_metadata", {}).get("id")
    metadata: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": "SerpApi Google Lens",
        "provider_search_id": search_id,
        "source_url": match.candidate.source_url,
        "source": match.candidate.source,
        "title": match.candidate.title,
        "discovered_image_url": match.candidate.image_url,
        "observed_at": observed_at,
        "search_rank": match.candidate.rank,
        "exact_visual_match": match.candidate.exact_match,
        "face_verification": {
            "detector": "OpenCV YuNet 2026may",
            "encoder": "OpenCV SFace 2021dec",
            "cosine_similarity": round(match.cosine_similarity, 6),
            "acceptance_threshold": similarity_threshold,
            "candidate_faces": match.detected_faces,
        },
        "identity": identity,
        "social_profiles": [profile.to_dict() for profile in social_profiles],
    }
    metadata_sha256 = sha256_bytes(canonical_json(metadata))
    chain_record = make_chain_record(
        content_sha256=content_sha256,
        source_url=match.candidate.source_url,
        observed_at=observed_at,
        metadata_sha256=metadata_sha256,
    )
    live.complete(
        "evidence",
        "Content and metadata fingerprints are ready for publication",
        content_sha256=content_sha256,
        metadata_sha256=metadata_sha256,
        chain_record=chain_record,
    )

    live.start("anchor", f"Publishing the evidence record to {chain_backend} Ethereum")
    chain = EthereumEvidenceChain(
        backend=chain_backend,
        rpc_url=os.getenv("SEPOLIA_RPC_URL"),
        private_key=os.getenv("SEPOLIA_PRIVATE_KEY"),
    )
    receipt = chain.publish(chain_record)
    live.complete("anchor", "The evidence transaction was mined", receipt=receipt.to_dict())

    live.start("verify", "Reading transaction calldata back from Ethereum")
    chain_verified = chain.verify(receipt.transaction_hash, chain_record)
    if not chain_verified:
        raise RuntimeError("on-chain record did not match the evidence written in this run")

    bundle: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": run_id,
        "input": {
            "filename": image_path.name,
            "detected_faces": input_face.detected_faces,
            "selected_face": "largest bounding box",
            "embedding_retained": False,
        },
        "match": {
            **match.candidate.to_dict(),
            "cosine_similarity": round(match.cosine_similarity, 6),
            "detected_faces": match.detected_faces,
            "local_image": matched_image_name,
            "content_sha256": content_sha256,
        },
        "metadata": metadata,
        "metadata_sha256": metadata_sha256,
        "identity": identity,
        "social_profiles": [profile.to_dict() for profile in social_profiles],
        "chain_record": chain_record,
        "blockchain": receipt.to_dict(),
        "verification": {
            "on_chain_record_matches": True,
            "verified_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "privacy": {
            "image_stored_on_chain": False,
            "face_embedding_stored": False,
            "on_chain_fields": sorted(chain_record),
        },
    }
    evidence_path = run_dir / "evidence.json"
    _write_json(evidence_path, bundle)
    live.complete(
        "verify",
        "The on-chain record exactly matches the evidence created in this run",
        checks={"on_chain_record_matches": True},
        evidence_path=str(evidence_path),
    )
    return evidence_path, bundle


def verify_sepolia_bundle(
    evidence_path: Path, *, image_path: Path | None = None
) -> dict[str, bool]:
    bundle = json.loads(evidence_path.read_text(encoding="utf-8"))
    blockchain = bundle["blockchain"]
    if blockchain["backend"] != "sepolia":
        raise ValueError(
            "standalone verification requires a persistent Sepolia transaction; "
            "local eth-tester records are re-verified during `run`"
        )
    resolved_image = image_path or evidence_path.parent / bundle["match"]["local_image"]
    image_hash_matches = (
        sha256_bytes(resolved_image.read_bytes()) == bundle["chain_record"]["content_sha256"]
    )
    metadata_hash_matches = (
        sha256_bytes(canonical_json(bundle["metadata"]))
        == bundle["chain_record"]["metadata_sha256"]
    )
    chain = EthereumEvidenceChain(
        backend="sepolia",
        rpc_url=os.getenv("SEPOLIA_RPC_URL"),
        private_key=None,
    )
    on_chain_record_matches = chain.verify(blockchain["transaction_hash"], bundle["chain_record"])
    return {
        "image_hash_matches": image_hash_matches,
        "metadata_hash_matches": metadata_hash_matches,
        "on_chain_record_matches": on_chain_record_matches,
        "verified": image_hash_matches and metadata_hash_matches and on_chain_record_matches,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _media_suffix(media_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(media_type.lower(), ".img")


def _data_url(content: bytes, media_type: str) -> str:
    return f"data:{media_type};base64," + base64.b64encode(content).decode("ascii")


def _image_preview(content: bytes) -> str:
    pixels = cv.imdecode(np.frombuffer(content, dtype=np.uint8), cv.IMREAD_COLOR)
    if pixels is None:
        return ""
    return _pixel_preview(pixels)


def _pixel_preview(pixels: np.ndarray) -> str:
    height, width = pixels.shape[:2]
    scale = min(1.0, 720 / max(height, width))
    if scale < 1:
        pixels = cv.resize(pixels, None, fx=scale, fy=scale, interpolation=cv.INTER_AREA)
    ok, encoded = cv.imencode(".jpg", pixels, [cv.IMWRITE_JPEG_QUALITY, 76])
    return _data_url(encoded.tobytes(), "image/jpeg") if ok else ""
