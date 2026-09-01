from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from facechain.canonical import SCHEMA, canonical_json, make_chain_record, sha256_bytes
from facechain.chain import EthereumEvidenceChain
from facechain.errors import FaceDetectionError, NoMatchError, SearchError
from facechain.face import SFACE_COSINE_THRESHOLD, FaceEngine, prepare_search_crop
from facechain.model_store import model_paths
from facechain.models import ConfirmedMatch
from facechain.search import SerpApiLens


def run_pipeline(
    image_path: Path,
    *,
    chain_backend: str = "local",
    artifact_root: Path = Path("artifacts"),
    model_dir: Path | None = None,
    max_candidates: int = 20,
    similarity_threshold: float = SFACE_COSINE_THRESHOLD,
) -> tuple[Path, dict[str, Any]]:
    if not image_path.is_file():
        raise FaceDetectionError(f"input image does not exist: {image_path}")
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key.strip():
        raise SearchError("SERPAPI_KEY is required for a genuine live search")
    observed_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    detector_model, recognizer_model = model_paths(model_dir)
    face_engine = FaceEngine(detector_model, recognizer_model)
    input_bytes = image_path.read_bytes()
    input_face = face_engine.encode_primary(input_bytes)
    search_crop = prepare_search_crop(input_face)

    with SerpApiLens(api_key) as search:
        candidates, raw_search = search.search(search_crop)
        _write_json(run_dir / "search-response.json", raw_search)
        if not candidates:
            raise NoMatchError("Google Lens returned no supported social-media results")

        confirmed: list[ConfirmedMatch] = []
        failures: list[dict[str, Any]] = []
        ranked = sorted(candidates, key=lambda item: (not item.exact_match, item.rank))
        for candidate in ranked[:max_candidates]:
            try:
                candidate_bytes, media_type = search.download_candidate(candidate)
                score, face_count = face_engine.best_similarity(input_face.feature, candidate_bytes)
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

    _write_json(run_dir / "candidate-diagnostics.json", failures)
    if not confirmed:
        raise NoMatchError(
            f"no social result passed SFace confirmation at threshold {similarity_threshold}"
        )

    match = max(confirmed, key=lambda item: item.cosine_similarity)
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
    }
    metadata_sha256 = sha256_bytes(canonical_json(metadata))
    chain_record = make_chain_record(
        content_sha256=content_sha256,
        source_url=match.candidate.source_url,
        observed_at=observed_at,
        metadata_sha256=metadata_sha256,
    )

    chain = EthereumEvidenceChain(
        backend=chain_backend,
        rpc_url=os.getenv("SEPOLIA_RPC_URL"),
        private_key=os.getenv("SEPOLIA_PRIVATE_KEY"),
    )
    receipt = chain.publish(chain_record)
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
