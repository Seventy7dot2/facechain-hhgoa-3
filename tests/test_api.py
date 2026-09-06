from pathlib import Path

from fastapi.testclient import TestClient

import facechain.api as api


def test_health_endpoint() -> None:
    response = TestClient(api.app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_rejects_unsupported_upload() -> None:
    response = TestClient(api.app).post(
        "/api/runs",
        files={"image": ("face.gif", b"not-an-image", "image/gif")},
        data={"chain": "local"},
    )
    assert response.status_code == 415


def test_run_endpoint_returns_frontend_summary(monkeypatch, tmp_path: Path) -> None:
    temporary_upload: Path | None = None

    def fake_run(path: Path, **_kwargs):
        nonlocal temporary_upload
        temporary_upload = path
        assert path.is_file()
        bundle = {
            "run_id": "run-123",
            "match": {
                "source_url": "https://x.com/example/status/1",
                "title": "Verified post",
                "source": "X",
                "cosine_similarity": 0.91,
                "content_sha256": "0xabc",
            },
            "identity": {"name": "Example Person", "kgmid": "/m/example"},
            "social_profiles": [],
            "blockchain": {
                "backend": "local",
                "chain_id": 1,
                "transaction_hash": "0xtx",
                "block_number": 1,
                "sender": "0xsender",
                "explorer_url": None,
            },
            "privacy": {"image_stored_on_chain": False},
        }
        return tmp_path / "evidence.json", bundle

    monkeypatch.setattr(api, "run_pipeline", fake_run)
    response = TestClient(api.app).post(
        "/api/runs",
        files={"image": ("face.webp", b"fake-webp", "image/webp")},
        data={"chain": "local"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert response.json()["identity"]["name"] == "Example Person"
    assert temporary_upload is not None
    assert not temporary_upload.exists()


def test_run_endpoint_streams_original_pipeline_events(monkeypatch, tmp_path: Path) -> None:
    temporary_upload: Path | None = None

    def fake_run(path: Path, **kwargs):
        nonlocal temporary_upload
        temporary_upload = path
        kwargs["progress"](
            {
                "id": 1,
                "run_id": "run-stream",
                "stage": "search",
                "state": "completed",
                "message": "Google Lens returned one candidate",
                "elapsed_ms": 42.5,
                "duration_ms": 40.0,
                "data": {"candidate_count": 1},
            }
        )
        bundle = {
            "run_id": "run-stream",
            "match": {
                "source_url": "https://github.com/example",
                "title": "Example Person · GitHub",
                "source": "GitHub",
                "cosine_similarity": 0.91,
                "content_sha256": "0xabc",
            },
            "identity": {"name": "Example Person", "kgmid": "/m/example"},
            "social_profiles": [
                {
                    "platform": "github",
                    "handle": "example",
                    "profile_url": "https://github.com/example",
                    "confidence": "knowledge_graph",
                }
            ],
            "blockchain": {
                "backend": "local",
                "chain_id": 1,
                "transaction_hash": "0xtx",
                "block_number": 1,
                "sender": "0xsender",
                "explorer_url": None,
            },
            "privacy": {"image_stored_on_chain": False},
        }
        return tmp_path / "evidence.json", bundle

    monkeypatch.setattr(api, "run_pipeline", fake_run)
    response = TestClient(api.app).post(
        "/api/runs",
        headers={"Accept": "text/event-stream"},
        files={"image": ("face.webp", b"fake-webp", "image/webp")},
        data={"chain": "local"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"stage": "search"' in response.text
    assert '"state": "finished"' in response.text
    assert '"handle": "example"' in response.text
    assert temporary_upload is not None
    assert not temporary_upload.exists()
