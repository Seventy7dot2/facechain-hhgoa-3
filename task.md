# HH Goa 2026 Shortlisting Task 3: Face Identification & Blockchain Verification

## What to Build

Build an end-to-end pipeline that takes a face scan as input, identifies matching content on the web/social media, and then verifies the discovered data using a blockchain.

**Pipeline:**

`Face scan input → Web/social media search → Find matching post → Blockchain upload/verification`

## Technical Requirements

### 1. Face Identification

Detect and encode a face from an input image.

Any face detection/recognition library or API is acceptable.

### 2. Social Media / Web Search

Use the face to search the web and find **at least one real, matching social media post**.

You may use:

- Reverse image search
- An API
- A scripted search approach

The search must be a **genuine search step** and not a hardcoded/pre-picked result.

### 3. Blockchain Verification

Once a matching post is found, upload the post or a hash/fingerprint of it to a blockchain to create a **verifiable, tamper-evident record**.

You can store, for example:

- Image
- Text
- Metadata
- Hash/fingerprint of the discovered content

**Any blockchain may be used**, including:

- Public testnet
- Mainnet
- Local/simulated blockchain

You must be able to demonstrate **re-verifying the data against the on-chain record**.

### 4. No Website Required

You do **not** need to build or host a project website.

Focus your time on the pipeline itself.

### 5. GitHub Repository Required

Your complete source code must be available in a GitHub repository.

The repository must include a `README.md` covering:

- What the project does
- How to run it
- Which blockchain was used
- Known limitations

## Submission Requirements

- GitHub repository link
