# FaceChain Frontend

Responsive HH Goa-themed interface for the FaceChain Evidence pipeline. It accepts a consented
JPG, PNG, or WebP upload, sends it to the Python API, visualizes pipeline progress, and presents
verified sources, supported social profiles, hashes, and blockchain receipts in a proof board.

```bash
cp .env.example .env.local
npm install
npm run dev
```

The default API URL is `http://localhost:8000`. Override `NEXT_PUBLIC_FACECHAIN_API_URL` when the
API is hosted elsewhere.

## Checks

```bash
npm run lint
npm test
```
