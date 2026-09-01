# FaceChain Evidence

FaceChain Evidence is a command-line pipeline for the HH Goa 2026 face identification and
blockchain verification challenge. It detects and encodes a face, performs a genuine Google Lens
search, locally confirms that a face in the discovered social-media image matches the input, and
resolves associated social profiles through Google's Knowledge Graph before anchoring a compact
evidence record on Ethereum.

```text
input image
    -> YuNet detection + SFace encoding
    -> SerpApi local-image upload + live Google Lens search
    -> social-domain filtering + SFace candidate confirmation
    -> Lens entity + Knowledge Graph social-profile lookup
    -> canonical evidence hashes
    -> Ethereum transaction
    -> independent read-back and verification
```

No website is required or included. Raw face embeddings are held only in memory. Social images are
never stored on-chain.

## What goes on-chain

Each successful run writes a versioned JSON envelope into an Ethereum transaction's calldata:

- SHA-256 of the exact discovered image bytes
- source social-post URL
- UTC observation timestamp
- SHA-256 of canonical discovery metadata

The metadata includes the search provider/result ID, title, source, image URL, search rank, model
names, face-similarity score, Lens entity, and associated social profiles. Knowledge Graph profiles
are marked `knowledge_graph`; profile-shaped organic results are marked `search_result` so the two
confidence levels are never conflated. The generated evidence bundle contains the transaction hash
and block number. Verification fetches the transaction, decodes its calldata, re-hashes the
off-chain image and metadata, and checks that all values agree.

## Quick start

Prerequisites: Python 3.11–3.13, [`uv`](https://docs.astral.sh/uv/), and a SerpApi key. SerpApi is
used because its Google Lens API accepts a local JPG/PNG/WebP upload and returns the live result set;
no result URL is hardcoded.

```bash
uv sync --extra dev
cp .env.example .env
# Add SERPAPI_KEY to .env; never commit this file.
uv run facechain download-models
uv run facechain inspect-face /path/to/one-face.jpg
uv run facechain run /path/to/one-face.jpg
```

The default `local` blockchain is Web3.py's in-process Ethereum tester. It mines a real Ethereum
transaction, returns a transaction and block hash, then reads the record back from the chain and
re-verifies it before reporting success. Run artifacts are written under `artifacts/<run-id>/` and
are ignored by Git because they can contain biometric imagery.

### Optional public Sepolia proof

For a persistent public record, fund a dedicated Sepolia test wallet and set:

```dotenv
SEPOLIA_RPC_URL=https://your-sepolia-rpc.example
SEPOLIA_PRIVATE_KEY=0x...
```

Then run and later re-verify the same record:

```bash
uv run facechain run /path/to/one-face.jpg --chain sepolia
uv run facechain verify artifacts/<run-id>/evidence.json
```

The evidence JSON includes an Etherscan link. Use a dedicated testnet-only private key; never reuse
a wallet that controls real assets.

## Output

A successful run saves:

- `evidence.json` — canonical metadata, hashes, chain receipt, and verification result
- `matched-content.*` — off-chain bytes whose hash was anchored
- `search-response.json` — sanitized live provider response (no API key)
- `profile-search-response.json` — sanitized entity/profile lookup evidence
- `candidate-diagnostics.json` — rejected candidates and reasons

Only sanitized metadata/receipt files should be copied into a public demo folder. Do not commit the
input image, matched image, face embeddings, `.env`, or the complete `artifacts/` directory.

## Quality checks

```bash
uv run ruff check .
uv run pytest --cov=facechain --cov-report=term-missing
```

Tests cover deterministic evidence encoding, URL filtering and live-response parsing, candidate
selection/orchestration, content tampering, and a full publish/read/verify cycle on simulated
Ethereum. Network calls are mocked in the test suite.

## Blockchain used

Ethereum is used in both modes:

- **Local default:** `EthereumTesterProvider` + Py-EVM, with pre-funded test accounts and instant
  mining. This mode is reproducible and requires no wallet, faucet, Docker, or external node.
- **Optional public mode:** Ethereum Sepolia through any standard JSON-RPC endpoint. Transactions
  are EIP-1559 signed locally and can be inspected on Etherscan.

A smart contract is deliberately unnecessary: immutable transaction calldata is sufficient for a
small append-only evidence envelope, reduces deployment complexity and gas, and works identically
on local Ethereum and Sepolia.

## Known limitations and responsible use

- Reverse-image coverage depends on Google Lens indexing, SerpApi availability/quota, and the
  social platform. A real person may have no indexed result.
- SFace similarity is evidence of visual similarity, not legal proof of identity. The OpenCV LFW
  cosine threshold (`0.363`) is used as a baseline and can produce false positives or negatives.
- The largest detected input face is selected. Use a clear, front-facing, single-person image.
- Some social CDNs block downloads or expire image URLs. Candidates that cannot be downloaded are
  recorded and skipped.
- Hashes verify the exact downloaded bytes. Re-encoded or resized copies will have different hashes
  even when visually identical.
- Local-chain state exists only for the process that performs the run; read-back verification is
  completed before exit. Use Sepolia when later independent verification is required.
- Public URLs and timestamps are public personal data when placed on a public chain. Run this only
  with informed consent and do not use it for surveillance, access control, or consequential
  identity decisions.
- A Knowledge Graph association is stronger than a generic search result but is still third-party
  metadata, not proof that an account is currently controlled by the identified person.

## Repository submission

This directory is ready to initialize and push as a GitHub repository. Before submission, perform a
consented live run, copy only sanitized metadata and the transaction receipt into the repository if
desired, review it for personal information, and add the resulting GitHub URL to the submission.
