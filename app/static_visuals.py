"""Static image renderer that serves pre-extracted diagram images from S3.

Instead of rendering PDF pages on-the-fly and base64-encoding them,
this module looks up pre-uploaded static images organized by PDF and page number.

S3 structure:
  static-images/<pdf-stem>/metadata.json
  static-images/<pdf-stem>/<filename>.png

The metadata.json maps image keys to page numbers and descriptions.
When a retrieval result points to a specific PDF page, this renderer
finds all static images associated with that page and returns presigned URLs.

Design:
  - One folder per PDF (e.g., static-images/hf2000_manual_tem_edx_nbd_dstem/)
  - metadata.json defines which images belong to which pages
  - Images are served via presigned S3 URLs (short-lived, no public bucket needed)
  - Multiple images per page are supported
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config as BotoConfig

from app.models import VisualReference
from config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticImage:
    """A single pre-extracted image for a PDF page."""

    image_url: str
    filename: str
    name: str
    description: str
    page_number: int
    highlights: dict  # highlight annotations from metadata


@dataclass(frozen=True)
class StaticVisualResult:
    """Result from looking up static images for a visual reference."""

    images: list[StaticImage]
    source: str
    page_number: int
    caption: str


class StaticImageRenderer(Protocol):
    def render(self, reference: VisualReference) -> StaticVisualResult | None: ...


class S3StaticImageRenderer:
    """Serves pre-uploaded static images from S3 via presigned URLs.

    Parameters
    ----------
    settings : Settings
        App settings (for S3 bucket, region, timeouts).
    s3_client : optional
        Injected S3 client (for testing).
    presign_expiry : int
        Presigned URL expiry in seconds (default: 1 hour).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        s3_client=None,
        presign_expiry: int = 3600,
        s3_bucket: str | None = None,
    ):
        if settings is None and (s3_client is None or s3_bucket is None):
            raise ValueError("settings or explicit dependencies are required")

        self.bucket = s3_bucket or settings.s3_bucket
        self.presign_expiry = presign_expiry

        if s3_client is not None:
            self.s3 = s3_client
        else:
            sdk_config = BotoConfig(
                connect_timeout=settings.aws_connect_timeout,
                read_timeout=settings.aws_read_timeout,
                retries={"max_attempts": settings.aws_max_attempts, "mode": "standard"},
            )
            self.s3 = boto3.client(
                "s3", region_name=settings.region, config=sdk_config
            )

        # Cache: pdf_stem -> parsed metadata dict
        self._metadata_cache: dict[str, dict | None] = {}

    def render(self, reference: VisualReference) -> StaticVisualResult | None:
        """Look up static images for the given visual reference.

        Returns None if no static images are available for this PDF/page.
        """
        pdf_stem = self._pdf_stem(reference.source)
        if not pdf_stem:
            return None

        metadata = self._load_metadata(pdf_stem)
        if metadata is None:
            return None

        # Find images for this page number
        page_images = self._images_for_page(
            metadata, pdf_stem, reference.page_number
        )
        if not page_images:
            return None

        return StaticVisualResult(
            images=page_images,
            source=reference.source,
            page_number=reference.page_number,
            caption=reference.caption,
        )

    def _pdf_stem(self, source_filename: str) -> str | None:
        """Extract the PDF stem (without extension) from the source filename."""
        if not source_filename:
            return None
        name = source_filename
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        return name

    @lru_cache(maxsize=32)
    def _load_metadata(self, pdf_stem: str) -> dict | None:
        """Load and cache metadata.json from S3 for a given PDF."""
        key = f"static-images/{pdf_stem}/metadata.json"
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            body = response.get("Body")
            if body is None:
                return None
            try:
                data = json.loads(body.read().decode("utf-8"))
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
            if not isinstance(data, dict):
                return None
            return data
        except self.s3.exceptions.NoSuchKey:
            logger.debug("no static images metadata for %s", pdf_stem)
            return None
        except Exception:
            logger.warning("failed to load static image metadata for %s", pdf_stem, exc_info=True)
            return None

    def _images_for_page(
        self, metadata: dict, pdf_stem: str, page_number: int
    ) -> list[StaticImage]:
        """Find all static images that belong to the given page number."""
        images: list[StaticImage] = []
        page_prefix = f"p{page_number}_"

        for image_key, image_data in metadata.items():
            # Match by page number prefix in the key (e.g., "p4_フラッシュ")
            if not image_key.startswith(page_prefix):
                continue

            filename = image_data.get("filename", "")
            if not filename:
                continue

            # Generate presigned URL
            s3_key = f"static-images/{pdf_stem}/{filename}"
            try:
                url = self.s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": s3_key},
                    ExpiresIn=self.presign_expiry,
                )
            except Exception:
                logger.warning("failed to generate presigned URL for %s", s3_key, exc_info=True)
                continue

            images.append(
                StaticImage(
                    image_url=url,
                    filename=filename,
                    name=image_data.get("name", image_key),
                    description=image_data.get("description", ""),
                    page_number=page_number,
                    highlights=image_data.get("highlights", {}),
                )
            )

        return images

    def clear_cache(self) -> None:
        """Clear the metadata cache (useful after uploading new images)."""
        self._load_metadata.cache_clear()
        self._metadata_cache.clear()
