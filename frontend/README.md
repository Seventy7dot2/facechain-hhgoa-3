# FaceChain Frontend

Responsive HH Goa-themed observatory for the complete FaceChain pipeline. It sends a consented JPG,
PNG, or WebP image to the original `/api/runs` endpoint and requests a real-time event stream. The
interface displays the detected face, exact search crop, Google Lens candidate images, SFace scores,
resolved social handles with provenance labels, evidence hashes, and blockchain receipt.

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
