from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from facechain.errors import SearchError
from facechain.models import SearchCandidate, SocialProfile

SOCIAL_HOSTS = (
    "bsky.app",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
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

    def discover_social_profiles(
        self, lens_payload: dict[str, Any]
    ) -> tuple[dict[str, str] | None, list[SocialProfile], dict[str, Any] | None]:
        """Resolve the Lens entity and its associated Knowledge Graph profiles."""
        identity = extract_identity_hint(lens_payload)
        if identity is None:
            return None, [], None
        params = {
            "api_key": self._api_key,
            "engine": "google",
            "q": identity["name"],
            "hl": "en",
            "safe": "active",
        }
        if identity.get("kgmid"):
            params["kgmid"] = identity["kgmid"]
        try:
            response = self._client.get(self.SEARCH_URL, params=params)
        except httpx.HTTPError as exc:
            raise SearchError(f"SerpApi entity profile search failed: {exc}") from exc
        payload = self._json_or_error(response, "entity profile search")
        knowledge_graph = payload.get("knowledge_graph")
        if isinstance(knowledge_graph, dict):
            identity["name"] = str(knowledge_graph.get("title") or identity["name"])
            identity["kgmid"] = str(knowledge_graph.get("kgmid") or identity.get("kgmid") or "")
        profiles = extract_social_profiles(payload)
        return identity, profiles, sanitize_profile_payload(payload)

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


def extract_identity_hint(payload: dict[str, Any]) -> dict[str, str] | None:
    related = payload.get("related_content")
    if not isinstance(related, list):
        return None
    for row in related:
        if not isinstance(row, dict) or not row.get("query"):
            continue
        link = str(row.get("serpapi_link") or row.get("link") or "")
        kgmid = parse_qs(urlparse(link).query).get("kgmid", [""])[0]
        return {
            "name": str(row["query"]),
            "kgmid": kgmid,
            "source": "google_lens_related_content",
        }
    return None


def extract_social_profiles(payload: dict[str, Any]) -> list[SocialProfile]:
    profiles: list[SocialProfile] = []
    seen: set[tuple[str, str]] = set()
    knowledge_graph = payload.get("knowledge_graph")
    rows = knowledge_graph.get("profiles", []) if isinstance(knowledge_graph, dict) else []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        profile = _social_profile(
            str(row.get("name") or ""),
            str(row.get("link") or ""),
            confidence="knowledge_graph",
        )
        if profile and (profile.platform, profile.handle.lower()) not in seen:
            seen.add((profile.platform, profile.handle.lower()))
            profiles.append(profile)

    organic = payload.get("organic_results", [])
    if not isinstance(organic, list):
        organic = []
    for row in organic:
        if not isinstance(row, dict):
            continue
        profile = _social_profile(
            str(row.get("source") or row.get("title") or ""),
            str(row.get("link") or ""),
            confidence="search_result",
        )
        if profile and (profile.platform, profile.handle.lower()) not in seen:
            seen.add((profile.platform, profile.handle.lower()))
            profiles.append(profile)
    return profiles


def sanitize_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    knowledge = payload.get("knowledge_graph")
    organic = payload.get("organic_results")
    return {
        "search_metadata": (
            {
                key: value
                for key, value in metadata.items()
                if key in {"id", "status", "created_at", "processed_at", "total_time_taken"}
            }
            if isinstance(metadata, dict)
            else {}
        ),
        "knowledge_graph": (
            {
                "title": knowledge.get("title"),
                "kgmid": knowledge.get("kgmid"),
                "profiles": knowledge.get("profiles", []),
            }
            if isinstance(knowledge, dict)
            else None
        ),
        "organic_results": (
            [
                {
                    key: row.get(key)
                    for key in ("position", "title", "link", "source")
                    if row.get(key) is not None
                }
                for row in organic
                if isinstance(row, dict)
            ]
            if isinstance(organic, list)
            else []
        ),
    }


def _social_profile(label: str, raw_url: str, *, confidence: str) -> SocialProfile | None:
    url = _repair_profile_url(raw_url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    medium_subdomain = host.endswith(".medium.com") and host != "medium.com"
    if not host or (not parts and not medium_subdomain) or not is_social_url(url):
        return None

    platform = _platform_name(host, label)
    blocked_first = {"explore", "home", "i", "p", "pin", "reel", "search", "stories", "watch"}
    blocked_later = {"posts", "reel", "status", "videos", "watch"}
    if parts and (
        parts[0].lower() in blocked_first
        or any(part.lower() in blocked_later for part in parts[1:])
    ):
        return None

    if medium_subdomain:
        handle = host.removesuffix(".medium.com")
    elif platform == "youtube" and parts[0].lower() in {"channel", "user", "c"}:
        if len(parts) < 2:
            return None
        handle = parts[1]
    elif platform == "youtube" and not parts[0].startswith("@"):
        return None
    elif platform == "linkedin" and parts[0].lower() in {"company", "in", "pub"}:
        if len(parts) < 2:
            return None
        handle = parts[1]
    else:
        handle = parts[0]
    if platform in {"instagram", "threads", "tiktok", "x"} and not handle.startswith("@"):
        handle = "@" + handle
    return SocialProfile(platform, handle, url, confidence)


def _repair_profile_url(url: str) -> str:
    url = url.replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u003f", "?")
    for marker in ("http://", "https://"):
        position = url.find(marker, 8)
        if position > 0:
            return url[position:]
    return url


def _platform_name(host: str, label: str) -> str:
    if host.endswith(("twitter.com", "x.com")):
        return "x"
    for name in ("facebook", "instagram", "linkedin", "medium", "pinterest", "threads", "tiktok"):
        if host.endswith(name + ".com"):
            return name
    if host.endswith(("youtube.com", "youtu.be")):
        return "youtube"
    return label.strip().lower() or host
