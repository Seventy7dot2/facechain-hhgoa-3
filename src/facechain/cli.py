from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from facechain.errors import FaceChainError
from facechain.face import FaceEngine
from facechain.model_store import default_model_dir, download_models, model_paths
from facechain.pipeline import run_pipeline, verify_sepolia_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="facechain",
        description="Discover matching social content and anchor its fingerprint on Ethereum.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    models_parser = subparsers.add_parser(
        "download-models", help="Download checksum-pinned OpenCV face models"
    )
    models_parser.add_argument("--model-dir", type=Path, default=default_model_dir())

    inspect_parser = subparsers.add_parser(
        "inspect-face", help="Detect and encode the primary face without searching"
    )
    inspect_parser.add_argument("image", type=Path)
    inspect_parser.add_argument("--model-dir", type=Path, default=default_model_dir())

    run_parser = subparsers.add_parser("run", help="Run discovery, anchoring, and verification")
    run_parser.add_argument("image", type=Path)
    run_parser.add_argument("--chain", choices=("local", "sepolia"), default="local")
    run_parser.add_argument("--model-dir", type=Path, default=default_model_dir())
    run_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    run_parser.add_argument("--max-candidates", type=int, default=20)

    verify_parser = subparsers.add_parser(
        "verify", help="Independently re-verify a persistent Sepolia evidence bundle"
    )
    verify_parser.add_argument("evidence", type=Path)
    verify_parser.add_argument("--image", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "download-models":
            paths = download_models(args.model_dir)
            print("Verified face models:")
            for path in paths:
                print(f"  {path}")
            return

        if args.command == "inspect-face":
            detector, recognizer = model_paths(args.model_dir)
            encoded = FaceEngine(detector, recognizer).encode_primary(args.image.read_bytes())
            print(
                json.dumps(
                    {
                        "detected_faces": encoded.detected_faces,
                        "selected_face": "largest bounding box",
                        "embedding_dimensions": int(encoded.feature.size),
                        "embedding_retained": False,
                    },
                    indent=2,
                )
            )
            return

        if args.command == "run":
            if args.max_candidates < 1:
                raise ValueError("--max-candidates must be at least 1")
            print("Running live face discovery and evidence anchoring...", flush=True)
            evidence_path, bundle = run_pipeline(
                args.image,
                chain_backend=args.chain,
                artifact_root=args.artifact_root,
                model_dir=args.model_dir,
                max_candidates=args.max_candidates,
            )
            summary = {
                "status": "verified",
                "source_url": bundle["match"]["source_url"],
                "cosine_similarity": bundle["match"]["cosine_similarity"],
                "content_sha256": bundle["match"]["content_sha256"],
                "chain": bundle["blockchain"]["backend"],
                "transaction_hash": bundle["blockchain"]["transaction_hash"],
                "block_number": bundle["blockchain"]["block_number"],
                "explorer_url": bundle["blockchain"]["explorer_url"],
                "identity": bundle["identity"],
                "social_profiles": bundle["social_profiles"],
                "evidence": str(evidence_path),
            }
            print(json.dumps(summary, indent=2))
            return

        result = verify_sepolia_bundle(args.evidence, image_path=args.image)
        print(json.dumps(result, indent=2))
        if not result["verified"]:
            raise SystemExit(1)
    except (FaceChainError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
