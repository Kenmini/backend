"""Upload static diagram images to S3 for serving via the backend.

Structure in S3:
  static-images/<pdf-stem>/<filename>.png
  static-images/<pdf-stem>/metadata.json

Usage:
  python scripts/upload_static_images.py <source_folder> [--bucket BUCKET]

Example:
  python scripts/upload_static_images.py ../frontend/public/images/diagrams --bucket bedrock-docs-ttanaka-202606
"""

import argparse
import json
import sys
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser(description="Upload static images to S3")
    parser.add_argument(
        "source_folder",
        type=Path,
        help="Local folder containing images and metadata.json",
    )
    parser.add_argument(
        "--bucket",
        default="bedrock-docs-ttanaka-202606",
        help="S3 bucket name (default: bedrock-docs-ttanaka-202606)",
    )
    parser.add_argument(
        "--pdf-stem",
        default=None,
        help="PDF stem name for S3 prefix. Auto-detected from folder name or metadata if not provided.",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without uploading",
    )
    args = parser.parse_args()

    source = args.source_folder.resolve()
    if not source.is_dir():
        print(f"Error: {source} is not a directory", file=sys.stderr)
        sys.exit(1)

    metadata_path = source / "metadata.json"
    if not metadata_path.exists():
        print(f"Error: {metadata_path} not found", file=sys.stderr)
        sys.exit(1)

    # Determine PDF stem
    pdf_stem = args.pdf_stem
    if not pdf_stem:
        # Use parent folder name as a heuristic, or default to a known name
        pdf_stem = source.name
        if pdf_stem == "diagrams":
            # The images are for the hf2000 manual
            pdf_stem = "hf2000_manual_tem_edx_nbd_dstem"
    
    s3_prefix = f"static-images/{pdf_stem}"
    print(f"Source folder: {source}")
    print(f"S3 destination: s3://{args.bucket}/{s3_prefix}/")
    print()

    # Collect files to upload
    files_to_upload: list[tuple[Path, str, str]] = []

    # Upload metadata.json
    files_to_upload.append((
        metadata_path,
        f"{s3_prefix}/metadata.json",
        "application/json",
    ))

    # Upload all image files
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    content_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    for file_path in sorted(source.iterdir()):
        if file_path.suffix.lower() in image_extensions:
            s3_key = f"{s3_prefix}/{file_path.name}"
            ct = content_types.get(file_path.suffix.lower(), "application/octet-stream")
            files_to_upload.append((file_path, s3_key, ct))

    print(f"Files to upload: {len(files_to_upload)}")
    print()

    if args.dry_run:
        for local, key, ct in files_to_upload:
            size_kb = local.stat().st_size / 1024
            print(f"  [DRY RUN] {local.name} -> s3://{args.bucket}/{key} ({size_kb:.1f} KB, {ct})")
        print("\nDry run complete. No files uploaded.")
        return

    # Upload
    s3 = boto3.client("s3", region_name=args.region)
    
    uploaded = 0
    failed = 0
    for local, key, ct in files_to_upload:
        try:
            s3.upload_file(
                str(local),
                args.bucket,
                key,
                ExtraArgs={"ContentType": ct},
            )
            size_kb = local.stat().st_size / 1024
            print(f"  ✓ {local.name} -> {key} ({size_kb:.1f} KB)")
            uploaded += 1
        except Exception as e:
            print(f"  ✗ {local.name} -> {key}: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {uploaded} uploaded, {failed} failed")


if __name__ == "__main__":
    main()
