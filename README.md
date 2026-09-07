# FaceChain Evidence — HH Goa 2026 Task 3

FaceChain Evidence is an end-to-end solution for **HH Goa Task 3: Face ID + Blockchain
Verification**.

It takes a face image, finds real matching social-media content through Google Lens, confirms the
face match locally, and writes a tamper-evident fingerprint to Ethereum. No search result is
hardcoded.

## Task 3 pipeline

```text
Input photo
  → YuNet face detection
  → SFace face encoding
  → SerpApi Google Lens reverse-image search
  → Local SFace confirmation of social results
  → Social profile discovery
  → SHA-256 evidence record
  → Ethereum transaction
  → On-chain read-back verification
```

## Quick start

Requirements:

- Python 3.11–3.13
- [uv](https://docs.astral.sh/uv/)
- A [SerpApi](https://serpapi.com/) API key

Install the project:

```bash
git clone https://github.com/Seventy7dot2/hhgoa-task-3.git
cd hhgoa-task-3
uv sync --extra dev
cp .env.example .env
```

Add your key to `.env`:

```dotenv
SERPAPI_KEY=your_serpapi_key
```

Download the checksum-verified face models once:

```bash
uv run facechain download-models
```

Run the complete Task 3 pipeline using the included sample:

```bash
uv run facechain run image.webp
```

`image.webp` is the sample input provided by the project owner for repository testing. Use other
face images only with the person's consent.

![Included sample input](image.webp)

## Result

The CLI prints:

- the real matched social profile or post URL;
- the local face-similarity score;
- discovered social handles;
- the content SHA-256 fingerprint;
- the Ethereum transaction hash and block number; and
- the saved evidence path.

Complete run evidence is written to `artifacts/<run-id>/evidence.json`. Candidate images and raw
provider responses remain off-chain.

## Blockchain

The default mode uses a local Ethereum chain through Web3.py's Ethereum tester. It publishes a real
transaction, reads the transaction data back, and verifies the record before the command succeeds.
No wallet, faucet, RPC service, or smart contract is required.

For a permanent public proof, add a dedicated Sepolia testnet RPC URL and private key to `.env`:

```dotenv
SEPOLIA_RPC_URL=https://your-sepolia-rpc.example
SEPOLIA_PRIVATE_KEY=0x_your_testnet_private_key
```

Then run:

```bash
uv run facechain run image.webp --chain sepolia
uv run facechain verify artifacts/<run-id>/evidence.json
```

Never use a wallet that controls real assets.

## Optional live frontend

The CLI is the primary Task 3 submission. The repository also includes an HH Goa-themed frontend
that visualizes every real backend stage and highlights the discovered profiles and posts.

Start it in two terminals:

```bash
# Terminal 1
uv run facechain serve
```

```bash
# Terminal 2
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000` and run the sample image. The event terminal is driven by backend
events; it does not simulate progress with frontend timers.

## Useful commands

```bash
# Confirm that a face can be detected without using SerpApi
uv run facechain inspect-face image.webp

# Inspect fewer Google Lens candidates
uv run facechain run image.webp --max-candidates 10

# Start the API used by the frontend
uv run facechain serve --host 127.0.0.1 --port 8000

# Run the automated checks
uv run ruff check .
uv run pytest
```

## What is stored on-chain?

Only a compact evidence record is stored in transaction calldata:

- hash of the exact matched image bytes;
- matched social source URL;
- observation timestamp; and
- hash of the canonical discovery metadata.

Images and face embeddings are never stored on-chain. Face embeddings remain in memory and are not
written to the evidence bundle.

## Known limitations

- Results depend on Google Lens indexing, SerpApi availability, and social-platform coverage.
- SFace similarity is supporting evidence, not proof of identity or account ownership.
- Similar-looking people can cause false positives; poor or side-profile images can cause false
  negatives.
- Some social-media CDNs block or expire image downloads, so those candidates may be skipped.
- The local Ethereum chain disappears after the process exits; use Sepolia for persistent proof.
- Public URLs written to Sepolia cannot be removed. Use the system only with informed consent.

## Responsible use

This project is a hackathon demonstration, not an identity authority. Do not use it for
surveillance, access control, employment, credit, policing, or other consequential decisions.
