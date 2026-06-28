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
import re
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
    # Presigned URL to the source PDF (fallback when no static images exist)
    pdf_url: str | None = None


class StaticImageRenderer(Protocol):
    def render(self, reference: VisualReference) -> StaticVisualResult | None: ...


# Generic words that appear in almost every lab question/diagram and therefore
# carry no relevance signal. Includes common UI/control vocabulary and panel
# location terms that show up on nearly every diagram, so they don't create
# spurious cross-page matches.
_STOPWORDS = frozenset(
    {
        # English
        "the", "a", "an", "is", "are", "was", "were", "be", "of", "to", "in",
        "on", "for", "and", "or", "our", "my", "your", "you", "we", "it", "this",
        "that", "with", "how", "what", "where", "when", "why", "who", "do", "does",
        "did", "can", "could", "should", "would", "i", "at", "by", "from", "as",
        "please", "check", "show", "tell", "me", "about", "page", "figure", "fig",
        "image", "photo", "diagram", "lab", "laboratory", "device", "equipment",
        # English UI / control vocabulary (low discriminative value)
        "switch", "button", "key", "knob", "dial", "lever", "lamp", "panel",
        "press", "left", "right", "main", "sub", "set", "turn",
        # Japanese (common particles / generic terms)
        "です", "ます", "する", "して", "した", "から", "まで", "こと", "もの",
        "ため", "よう", "この", "その", "あの", "どの", "ください", "教えて",
        "研究室", "装置", "確認", "について", "ですか", "ますか",
        # Japanese UI / control vocabulary and panel-location terms
        "スイ", "イッ", "ッチ",  # スイッチ (switch)
        "ボタ", "タン",          # ボタン (button)
        "つま", "まみ",          # つまみ (knob)
        "ダイ", "イヤ", "ヤル",  # ダイヤル (dial)
        "レバ", "バー",          # レバー (lever)
        "ラン", "ンプ",          # ランプ (lamp)
        "パネ", "ネル",          # パネル (panel)
        "メイ", "イン",          # メイン (main)
        "左メ", "右メ",          # 左/右メイン
    }
)


def _tokenize(text: str) -> set[str]:
    """Tokenize text into a set of comparable tokens.

    Handles bilingual (English + Japanese) content:
    - Latin words are lowercased and split on non-alphanumerics.
    - CJK runs are broken into adjacent-character bigrams, which approximate
      word matching without a Japanese tokenizer. Single CJK characters are
      intentionally excluded: like single English letters they are far too
      common (particles を/に/し/て...) and create spurious overlap.
    """
    if not text:
        return set()
    lowered = text.lower()
    tokens: set[str] = set()

    for word in re.findall(r"[a-z0-9]+", lowered):
        if len(word) > 1 and word not in _STOPWORDS:
            tokens.add(word)

    # Split into CJK runs so bigrams never straddle non-CJK boundaries.
    for run in re.findall(r"[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]+", lowered):
        for first, second in zip(run, run[1:]):
            bigram = first + second
            if bigram not in _STOPWORDS:
                tokens.add(bigram)

    return tokens


def image_relevance_score(query_text: str, image: StaticImage) -> int:
    """Keyword-overlap score between a query and a static image's metadata.

    Higher means more relevant. The query should combine the user's question
    and the generated answer for the best signal.
    """
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return 0

    parts = [image.name or "", image.description or ""]
    for highlight in (image.highlights or {}).values():
        if isinstance(highlight, dict):
            parts.append(str(highlight.get("item", "")))
            parts.append(str(highlight.get("explanation", "")))
            parts.append(str(highlight.get("annotation", "")))
    doc_tokens = _tokenize(" ".join(parts))

    return len(query_tokens & doc_tokens)


def filter_relevant_images(
    query_text: str, images: list[StaticImage], min_score: int
) -> list[StaticImage]:
    """Keep only images whose relevance score meets the minimum threshold."""
    scored = [
        (image_relevance_score(query_text, image), image) for image in images
    ]
    relevant = [image for score, image in scored if score >= min_score]
    # If nothing clears the bar, return empty (caller decides on fallback).
    return relevant


def keyword_relevant_indices(
    query_text: str, descriptions: list[str], min_score: int
) -> list[int]:
    """Return indices of descriptions whose keyword overlap meets the threshold.

    Used as a fallback when the model-based relevance gate is unavailable.
    """
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []
    kept: list[int] = []
    for index, description in enumerate(descriptions):
        if len(query_tokens & _tokenize(description or "")) >= min_score:
            kept.append(index)
    return kept


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

        Always returns a result when the source is a valid PDF:
        - If static images exist for the page, returns them.
        - If not, returns an empty images list with a presigned PDF URL as fallback.
        Returns None only if the source is not a recognized PDF.
        """
        pdf_stem = self._pdf_stem(reference.source)
        if not pdf_stem:
            return None

        metadata = self._load_metadata(pdf_stem)

        # Find static images for this page (may be empty)
        page_images: list[StaticImage] = []
        if metadata is not None:
            page_images = self._images_for_page(
                metadata, pdf_stem, reference.page_number
            )

        # Generate presigned URL to the original PDF as fallback
        pdf_url = self._presign_pdf(reference.source_uri)

        if not page_images and pdf_url is None:
            return None

        return StaticVisualResult(
            images=page_images,
            source=reference.source,
            page_number=reference.page_number,
            caption=reference.caption,
            pdf_url=pdf_url,
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

    def _presign_pdf(self, source_uri: str) -> str | None:
        """Generate a presigned URL for the original PDF in S3."""
        from urllib.parse import unquote, urlsplit

        parsed = urlsplit(source_uri)
        if parsed.scheme != "s3" or not parsed.netloc:
            return None
        key = unquote(parsed.path.lstrip("/"))
        if not key.lower().endswith(".pdf"):
            return None
        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": parsed.netloc, "Key": key},
                ExpiresIn=self.presign_expiry,
            )
        except Exception:
            logger.warning("failed to generate presigned PDF URL for %s", source_uri, exc_info=True)
            return None

    def clear_cache(self) -> None:
        """Clear the metadata cache (useful after uploading new images)."""
        self._load_metadata.cache_clear()
        self._metadata_cache.clear()
