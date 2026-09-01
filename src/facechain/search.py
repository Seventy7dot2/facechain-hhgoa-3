from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx

from facechain.errors import SearchError
from facechain.models import SearchCandidate

SOCIAL_HOSTS = (
    "bsky.app",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtu.be",
    "youtube.com",
)


class SerpApiLens:
    UPLOAD_URL = "https://serpapi.com/image"
    SEARCH_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, *, timeout: float = 45.0) -> None:
        if not api_key.strip():
            raise SearchError("SERPAPI_KEY is required for a genuine live search")
        self._api_key = api_key
        self._client = httpx.Client(follow_redirects=True, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SerpApiLens:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, face_jpeg: bytes) -> tuple[list[SearchCandidate], dict[str, Any]]:
        try:
            upload = self._client.post(
                self.UPLOAD_URL,
                data={"api_key": self._api_key},
                files={"image": ("face-search.jpg", face_jpeg, "image/jpeg")},
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"SerpApi image upload failed: {exc}") from exc
        upload_data = self._json_or_error(upload, "image upload")
        image_id = upload_data.get("image_id")
        if not image_id:
            raise SearchError("SerpApi image upload did not return an image_id")

        try:
            response = self._client.get(
                self.SEARCH_URL,
                params={
                    "api_key": self._api_key,
                    "engine": "google_lens",
                    "image_id": image_id,
                    "type": "all",
                    "hl": "en",
                    "safe": "active",
                },
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"SerpApi Google Lens search failed: {exc}") from exc
        payload = self._json_or_error(response, "Google Lens search")
        candidates = list(_parse_social_candidates(payload))
        return candidates, sanitize_search_payload(payload)

    def download_candidate(self, candidate: SearchCandidate) -> tuple[bytes, str]:
        errors: list[str] = []
        for url in (candidate.image_url, candidate.thumbnail_url):
            if not url:
                continue
            try:
                response = self._client.get(url)
                response.raise_for_status()
                media_type = response.headers.get("content-type", "").split(";", 1)[0]
                if not media_type.startswith("image/"):
                    raise ValueError(f"unexpected content type {media_type or 'unknown'}")
                if len(response.content) > 15_000_000:
                    raise ValueError("image exceeds the 15 MB safety limit")
                return response.content, media_type
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(str(exc))
        raise SearchError("candidate image download failed: " + "; ".join(errors))

    @staticmethod
    def _json_or_error(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"SerpApi {operation} failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise SearchError(f"SerpApi {operation} returned an invalid response")
        if payload.get("error"):
            raise SearchError(f"SerpApi {operation} failed: {payload['error']}")
        return payload


def is_social_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == suffix or host.endswith("." + suffix) for suffix in SOCIAL_HOSTS)


def _parse_social_candidates(payload: dict[str, Any]) -> Iterable[SearchCandidate]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    exact_rows = payload.get("exact_matches", [])
    if not isinstance(exact_rows, list):
        exact_rows = []
    for key in ("visual_matches", "exact_matches"):
        value = payload.get(key, [])
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))

    for index, row in enumerate(rows, start=1):
        source_url = str(row.get("link") or "")
        image_url = str(row.get("image") or row.get("thumbnail") or "")
        if not source_url or not image_url or not is_social_url(source_url):
            continue
        if source_url in seen:
            continue
        seen.add(source_url)
        yield SearchCandidate(
            rank=int(row.get("position") or index),
            title=str(row.get("title") or "Untitled social result"),
            source=str(row.get("source") or urlparse(source_url).hostname or "Unknown"),
            source_url=source_url,
            image_url=image_url,
            thumbnail_url=str(row.get("thumbnail")) if row.get("thumbnail") else None,
            exact_match=bool(row.get("exact_matches")) or row in exact_rows,
        )


def sanitize_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain useful provider evidence while removing temporary/private endpoints."""
    safe = dict(payload)
    safe.pop("search_parameters", None)
    metadata = safe.get("search_metadata")
    if isinstance(metadata, dict):
        safe["search_metadata"] = {
            key: value
            for key, value in metadata.items()
            if key in {"id", "status", "created_at", "processed_at", "total_time_taken"}
        }
    return safe
