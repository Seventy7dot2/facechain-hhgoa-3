import pytest

from facechain.canonical import (
    canonical_json,
    decode_chain_record,
    encode_chain_record,
    make_chain_record,
    sha256_bytes,
)


def sample_record() -> dict[str, str]:
    return make_chain_record(
        content_sha256="0x" + "a" * 64,
        source_url="https://x.com/example/status/1",
        observed_at="2026-09-01T12:00:00Z",
        metadata_sha256="0x" + "b" * 64,
    )


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})


def test_chain_record_round_trip() -> None:
    record = sample_record()
    assert decode_chain_record(encode_chain_record(record)) == record


def test_rejects_unprefixed_data() -> None:
    with pytest.raises(ValueError, match="not a FaceChain"):
        decode_chain_record(b'{"schema":"facechain.evidence.v1"}')


def test_exact_byte_hash_detects_tampering() -> None:
    assert sha256_bytes(b"image") != sha256_bytes(b"image!")
