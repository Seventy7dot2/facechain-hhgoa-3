from facechain.canonical import make_chain_record
from facechain.chain import EthereumEvidenceChain


def test_local_ethereum_publish_read_and_verify() -> None:
    record = make_chain_record(
        content_sha256="0x" + "1" * 64,
        source_url="https://x.com/example/status/123",
        observed_at="2026-09-01T12:00:00Z",
        metadata_sha256="0x" + "2" * 64,
    )
    chain = EthereumEvidenceChain(backend="local")
    receipt = chain.publish(record)
    assert receipt.backend == "local"
    assert receipt.block_number >= 1
    assert chain.read_record(receipt.transaction_hash) == record
    assert chain.verify(receipt.transaction_hash, record)
    assert not chain.verify(receipt.transaction_hash, {**record, "source_url": "tampered"})
