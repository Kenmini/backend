import base64
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import unquote, urlsplit

import boto3
import pymupdf
from botocore.config import Config as BotoConfig

from app.models import VisualReference
from config import Settings


class VisualRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderedVisual:
    image_url: str
    source: str
    page_number: int
    caption: str


class PdfPageRenderer(Protocol):
    def render(self, reference: VisualReference) -> RenderedVisual: ...


class S3PdfPageRenderer:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        s3_client=None,
        max_pdf_bytes: int | None = None,
    ):
        if settings is None and (s3_client is None or max_pdf_bytes is None):
            raise ValueError("settings or explicit renderer dependencies are required")
        self.max_pdf_bytes = (
            max_pdf_bytes
            if max_pdf_bytes is not None
            else settings.visual_max_pdf_bytes
        )
        if s3_client is not None:
            self.s3 = s3_client
        else:
            sdk_config = BotoConfig(
                connect_timeout=settings.aws_connect_timeout,
                read_timeout=settings.aws_read_timeout,
                retries={"max_attempts": settings.aws_max_attempts, "mode": "standard"},
            )
            self.s3 = boto3.client("s3", region_name=settings.region, config=sdk_config)

    def render(self, reference: VisualReference) -> RenderedVisual:
        image_url = self._render_page(reference.source_uri, reference.page_number)
        return RenderedVisual(
            image_url=image_url,
            source=reference.source,
            page_number=reference.page_number,
            caption=reference.caption,
        )

    @lru_cache(maxsize=16)
    def _render_page(self, source_uri: str, page_number: int) -> str:
        image = self._render_page_bytes(source_uri, page_number)
        encoded = base64.b64encode(image).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @lru_cache(maxsize=16)
    def _render_page_bytes(self, source_uri: str, page_number: int) -> bytes:
        """Render a single PDF page to JPEG bytes."""
        parsed = urlsplit(source_uri)
        key = unquote(parsed.path.lstrip("/"))
        if (
            parsed.scheme != "s3"
            or not parsed.netloc
            or not key.lower().endswith(".pdf")
        ):
            raise VisualRenderError("visual source must be an S3 PDF")

        response = self.s3.get_object(Bucket=parsed.netloc, Key=key)
        content_length = response.get("ContentLength")
        if isinstance(content_length, int) and content_length > self.max_pdf_bytes:
            self._close_body(response.get("Body"))
            raise VisualRenderError("PDF is too large to render")

        body = response.get("Body")
        if body is None:
            raise VisualRenderError("S3 response did not contain a PDF body")
        try:
            data = body.read(self.max_pdf_bytes + 1)
        finally:
            self._close_body(body)
        if len(data) > self.max_pdf_bytes:
            raise VisualRenderError("PDF is too large to render")

        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise VisualRenderError("PDF could not be opened") from exc
        try:
            if page_number < 1 or page_number > document.page_count:
                raise VisualRenderError("PDF page number is out of range")
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(1.25, 1.25),
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            image = pixmap.tobytes("jpeg", jpg_quality=72)
        finally:
            document.close()
        return image

    @staticmethod
    def _close_body(body) -> None:
        close = getattr(body, "close", None)
        if callable(close):
            close()
