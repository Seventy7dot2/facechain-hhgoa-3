from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    rank: int
    title: str
    source: str
    source_url: str
    image_url: str
    thumbnail_url: str | None = None
    exact_match: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConfirmedMatch:
    candidate: SearchCandidate
    cosine_similarity: float
    image_bytes: bytes
    image_media_type: str
    detected_faces: int


@dataclass(frozen=True, slots=True)
class ChainReceipt:
    backend: str
    chain_id: int
    transaction_hash: str
    block_number: int
    sender: str
    transaction_input: str
    explorer_url: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
