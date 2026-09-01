from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from eth_account import Account
from web3 import EthereumTesterProvider, HTTPProvider, Web3
from web3.exceptions import TransactionNotFound

from facechain.canonical import decode_chain_record, encode_chain_record
from facechain.errors import ChainError, ConfigurationError
from facechain.models import ChainReceipt


class EthereumEvidenceChain:
    """Writes compact evidence JSON into immutable Ethereum transaction calldata."""

    def __init__(
        self,
        *,
        backend: str,
        rpc_url: str | None = None,
        private_key: str | None = None,
    ) -> None:
        self.backend = backend
        self._private_key = private_key
        if backend == "local":
            self.web3 = Web3(EthereumTesterProvider())
            self._sender = self.web3.eth.accounts[0]
        elif backend == "sepolia":
            if not rpc_url:
                raise ConfigurationError("SEPOLIA_RPC_URL is required for Sepolia mode")
            self.web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 45}))
            if not self.web3.is_connected():
                raise ChainError("could not connect to the configured Sepolia RPC endpoint")
            self._sender = Account.from_key(private_key).address if private_key else None
        else:
            raise ConfigurationError(f"unsupported chain backend: {backend}")

    def publish(self, record: Mapping[str, Any]) -> ChainReceipt:
        if self.backend == "sepolia" and not self._private_key:
            raise ConfigurationError("SEPOLIA_PRIVATE_KEY is required to publish on Sepolia")
        payload = encode_chain_record(record)
        try:
            if self.backend == "local":
                transaction_hash = self.web3.eth.send_transaction(
                    {
                        "from": self._sender,
                        "to": self._sender,
                        "value": 0,
                        "data": payload,
                    }
                )
            else:
                transaction_hash = self._send_signed(payload)
            receipt = self.web3.eth.wait_for_transaction_receipt(transaction_hash, timeout=120)
            if receipt["status"] != 1:
                raise ChainError("evidence transaction was mined but reverted")
            transaction = self.web3.eth.get_transaction(transaction_hash)
        except ChainError:
            raise
        except Exception as exc:
            raise ChainError(f"evidence transaction failed: {exc}") from exc

        tx_hash = _hex(transaction_hash)
        tx_input = _hex(transaction.get("input", transaction.get("data", b"")))
        return ChainReceipt(
            backend=self.backend,
            chain_id=int(self.web3.eth.chain_id),
            transaction_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            sender=str(transaction["from"]),
            transaction_input=tx_input,
            explorer_url=(
                f"https://sepolia.etherscan.io/tx/{tx_hash}" if self.backend == "sepolia" else None
            ),
        )

    def read_record(self, transaction_hash: str) -> dict[str, Any]:
        try:
            transaction = self.web3.eth.get_transaction(transaction_hash)
        except TransactionNotFound as exc:
            raise ChainError(f"transaction not found: {transaction_hash}") from exc
        except Exception as exc:
            raise ChainError(f"could not read evidence transaction: {exc}") from exc
        raw = transaction.get("input", transaction.get("data", b""))
        try:
            return decode_chain_record(_hex(raw))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ChainError(
                f"transaction does not contain valid FaceChain evidence: {exc}"
            ) from exc

    def verify(self, transaction_hash: str, expected: Mapping[str, Any]) -> bool:
        return self.read_record(transaction_hash) == dict(expected)

    def _send_signed(self, payload: bytes) -> bytes:
        assert self._private_key is not None
        assert self._sender is not None
        base = {
            "chainId": self.web3.eth.chain_id,
            "nonce": self.web3.eth.get_transaction_count(self._sender, "pending"),
            "from": self._sender,
            "to": self._sender,
            "value": 0,
            "data": payload,
        }
        base["gas"] = self.web3.eth.estimate_gas(base)
        gas_price = self.web3.eth.gas_price
        try:
            priority_fee = self.web3.eth.max_priority_fee
        except Exception:
            priority_fee = self.web3.to_wei(1, "gwei")
        base["maxPriorityFeePerGas"] = priority_fee
        base["maxFeePerGas"] = max(gas_price * 2, priority_fee * 2)
        signed = self.web3.eth.account.sign_transaction(base, self._private_key)
        return self.web3.eth.send_raw_transaction(signed.raw_transaction)


def _hex(value: Any) -> str:
    if isinstance(value, str):
        return value if value.startswith("0x") else "0x" + value
    if hasattr(value, "hex"):
        result = value.hex()
        return result if result.startswith("0x") else "0x" + result
    return "0x" + bytes(value).hex()
