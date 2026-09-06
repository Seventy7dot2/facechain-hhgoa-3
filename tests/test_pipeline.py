from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import facechain.pipeline as pipeline
from facechain.face import FaceEncoding
from facechain.models import ChainReceipt, SearchCandidate


class FakeFaceEngine:
    def __init__(self, *_: object) -> None:
        pass

    def encode_primary(self, _image: bytes) -> FaceEncoding:
        pixels = np.full((100, 100, 3), 128, dtype=np.uint8)
        row = np.array([20, 20, 60, 60] + [0] * 11, dtype=np.float32)
        return FaceEncoding(pixels, np.zeros((1, 128)), row, 1)

    def best_similarity(self, _feature: np.ndarray, image: bytes) -> tuple[float, int]:
        return (0.91, 1) if image == b"winning-image" else (0.1, 1)


class FakeSearch:
    def __init__(self, _key: str) -> None:
        pass

    def __enter__(self) -> FakeSearch:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def search(self, _crop: bytes):
        candidates = [
            SearchCandidate(
                1,
                "False visual result",
                "X",
                "https://x.com/user/status/false",
                "https://cdn.example/false.jpg",
                exact_match=True,
            ),
            SearchCandidate(
                2,
                "Confirmed post",
                "Instagram",
                "https://instagram.com/p/confirmed",
                "https://cdn.example/good.jpg",
            ),
        ]
        return candidates, {"search_metadata": {"id": "live-search-123", "status": "Success"}}

    def download_candidate(self, candidate: SearchCandidate) -> tuple[bytes, str]:
        if "confirmed" in candidate.source_url:
            return b"winning-image", "image/jpeg"
        return b"wrong-image", "image/jpeg"

    def discover_social_profiles(self, _payload):
        from facechain.models import SocialProfile

        identity = {
            "name": "Test Person",
            "kgmid": "/m/test",
            "source": "google_lens_related_content",
        }
        profiles = [
            SocialProfile(
                "instagram", "@testperson", "https://instagram.com/testperson", "knowledge_graph"
            )
        ]
        return identity, profiles, {"knowledge_graph": {"title": "Test Person"}}


class FakeChain:
    def __init__(self, **_: object) -> None:
        pass

    def publish(self, record):
        self.record = dict(record)
        return ChainReceipt(
            backend="local",
            chain_id=131277322940537,
            transaction_hash="0xabc",
            block_number=1,
            sender="0xsender",
            transaction_input="0xdata",
            explorer_url=None,
        )

    def verify(self, _transaction_hash: str, expected) -> bool:
        return self.record == dict(expected)


def test_pipeline_selects_confirmed_face_and_keeps_biometrics_off_chain(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    monkeypatch.setattr(pipeline, "model_paths", lambda _root: (Path("a"), Path("b")))
    monkeypatch.setattr(pipeline, "FaceEngine", FakeFaceEngine)
    monkeypatch.setattr(pipeline, "SerpApiLens", FakeSearch)
    monkeypatch.setattr(pipeline, "EthereumEvidenceChain", FakeChain)
    image = tmp_path / "input.jpg"
    image.write_bytes(b"input-image")

    events = []
    evidence_path, bundle = pipeline.run_pipeline(
        image, artifact_root=tmp_path / "artifacts", progress=events.append
    )

    assert evidence_path.is_file()
    assert bundle["match"]["source_url"] == "https://instagram.com/p/confirmed"
    assert bundle["verification"]["on_chain_record_matches"] is True
    assert bundle["privacy"]["image_stored_on_chain"] is False
    assert bundle["input"]["embedding_retained"] is False
    assert bundle["identity"]["name"] == "Test Person"
    assert bundle["social_profiles"][0]["handle"] == "@testperson"
    assert "winning-image" not in json.dumps(bundle)
    assert set(bundle["chain_record"]) == {
        "schema",
        "content_sha256",
        "source_url",
        "observed_at",
        "metadata_sha256",
    }
    completed_stages = [event["stage"] for event in events if event["state"] == "completed"]
    assert completed_stages == [
        "input",
        "crop",
        "search",
        "profiles",
        "confirm",
        "evidence",
        "anchor",
        "verify",
    ]
    crop_event = next(
        event for event in events if event["stage"] == "crop" and event["state"] == "completed"
    )
    input_event = next(
        event for event in events if event["stage"] == "input" and event["state"] == "completed"
    )
    assert input_event["data"]["preview"].startswith("data:image/jpeg;base64,")
    assert crop_event["data"]["preview"].startswith("data:image/jpeg;base64,")
    assert events[-1]["data"]["checks"]["on_chain_record_matches"] is True
