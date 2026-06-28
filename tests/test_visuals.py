import base64
from io import BytesIO

import pymupdf
import pytest

from app.models import VisualReference
from app.visuals import S3PdfPageRenderer, VisualRenderError


def pdf_bytes(page_count=1):
    document = pymupdf.open()
    for index in range(page_count):
        page = document.new_page()
        page.insert_text((72, 72), f"HF-2000 page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


class FakeS3:
    def __init__(self, data, *, content_length=None):
        self.data = data
        self.content_length = len(data) if content_length is None else content_length
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ContentLength": self.content_length,
            "Body": BytesIO(self.data),
        }


def reference(page_number=1, uri="s3://lab-docs/manual.pdf"):
    return VisualReference(
        source_uri=uri,
        source="manual.pdf",
        page_number=page_number,
        caption="Sample holder instructions",
        score=0.8,
    )


def test_renderer_returns_cached_jpeg_data_url():
    s3 = FakeS3(pdf_bytes())
    renderer = S3PdfPageRenderer(s3_client=s3, max_pdf_bytes=1_000_000)

    first = renderer.render(reference())
    second = renderer.render(reference())

    assert first == second
    assert first.image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(first.image_url.split(",", 1)[1]).startswith(b"\xff\xd8")
    assert first.source == "manual.pdf"
    assert first.page_number == 1
    assert first.caption == "Sample holder instructions"
    assert len(s3.calls) == 1
    assert s3.calls[0] == {"Bucket": "lab-docs", "Key": "manual.pdf"}


def test_renderer_rejects_oversized_pdf_before_reading():
    renderer = S3PdfPageRenderer(
        s3_client=FakeS3(b"small", content_length=101), max_pdf_bytes=100
    )

    with pytest.raises(VisualRenderError, match="too large"):
        renderer.render(reference())


def test_renderer_rejects_invalid_page_and_non_pdf_source():
    renderer = S3PdfPageRenderer(s3_client=FakeS3(pdf_bytes()), max_pdf_bytes=1_000_000)

    with pytest.raises(VisualRenderError, match="page"):
        renderer.render(reference(page_number=2))
    with pytest.raises(VisualRenderError, match="PDF"):
        renderer.render(reference(uri="s3://lab-docs/minutes.docx"))
