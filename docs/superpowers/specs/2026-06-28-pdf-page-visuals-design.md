# Retrieved PDF Page Visuals

## Goal

Return a real visual from the HF-2000 PDF with a grounded `/ask` answer without
creating another Bedrock Knowledge Base or changing the frontend UI.

## Design

Bedrock retrieval already returns the source S3 URI and one-based PDF page
number for text chunks. The provider will retain the highest-ranked valid PDF
reference only after Sonnet accepts the answer as supported. A dedicated visual
renderer will download the referenced PDF with bounded reads, render that page
as a compressed JPEG with PyMuPDF, and return an inline data URL.

`visual_data` keeps its existing fields and gains optional `image_url`,
`source`, `page_number`, and `caption` fields. The URL is inline so localhost,
Cloudflare, and token-protected demos need no additional image endpoint. The
frontend can display it directly with an `<img>` element.

## Safety and fallback

- Only S3 PDF references produced by Bedrock retrieval are accepted.
- PDF downloads are bounded by `VISUAL_MAX_PDF_BYTES`.
- Only one page is rendered per answer and the renderer caches recent pages.
- Knowledge gaps never return retrieved PDF visuals.
- Download, parsing, or rendering failures are logged without changing the
  HTTP 200 answer contract.
- Demo fixtures and the existing static hotspot mapping continue to work.

## Acceptance

- A grounded HF-2000 question returns a JPEG data URL, source filename, page
  number, and source-text caption.
- A gap, DOCX-only result, invalid page, oversized file, or S3 error returns no
  extracted image and never crashes `/ask`.
- Unit, API contract, live smoke, and manual visual inspection pass.
