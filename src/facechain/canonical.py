from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA = "facechain.evidence.v1"
PAYLOAD_PREFIX = b"FACECHAIN:v1:"


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON suitable for hashing and transaction calldata."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()


def make_chain_record(
    *, content_sha256: str, source_url: str, observed_at: str, metadata_sha256: str
) -> dict[str, str]:
    return {
        "schema": SCHEMA,
        "content_sha256": content_sha256,
        "source_url": source_url,
        "observed_at": observed_at,
        "metadata_sha256": metadata_sha256,
    }


def encode_chain_record(record: Mapping[str, Any]) -> bytes:
    return PAYLOAD_PREFIX + canonical_json(record)


def decode_chain_record(data: bytes | str) -> dict[str, Any]:
    raw = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else data
    if not raw.startswith(PAYLOAD_PREFIX):
        raise ValueError("transaction data is not a FaceChain v1 evidence record")
    value = json.loads(raw[len(PAYLOAD_PREFIX) :].decode("utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unsupported evidence schema")
    return value
