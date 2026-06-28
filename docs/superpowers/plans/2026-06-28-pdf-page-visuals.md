# PDF Page Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return the relevant rendered HF-2000 PDF page in `/ask` visual data.

**Architecture:** Bedrock retains a validated S3 PDF/page reference alongside
the answer. A focused renderer downloads and renders one bounded PDF page;
FastAPI adds the result to the backward-compatible response and degrades safely
when rendering is unavailable.

**Tech Stack:** FastAPI, boto3, PyMuPDF, Pydantic, pytest, PowerShell

---

### Task 1: Preserve retrieval visual references

**Files:**
- Modify: `app/models.py`
- Modify: `app/providers.py`
- Test: `tests/test_providers.py`

- [ ] Add a failing provider test asserting a supported PDF result preserves
  its S3 URI, source filename, page number, caption, and score.
- [ ] Run `pytest tests/test_providers.py -q` and confirm the missing
  `visual_reference` assertion fails.
- [ ] Add `VisualReference` and the optional `AnswerResult.visual_reference`;
  select only valid one-based PDF page metadata from retrieved results.
- [ ] Verify supported answers pass and gaps contain no visual reference.

### Task 2: Render a bounded PDF page

**Files:**
- Create: `app/visuals.py`
- Modify: `requirements.txt`
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_visuals.py`
- Test: `tests/test_config.py`

- [ ] Add failing tests for S3 URI parsing, page rendering, cache reuse,
  oversized documents, invalid pages, and non-PDF sources.
- [ ] Run `pytest tests/test_visuals.py tests/test_config.py -q` and confirm the
  new module/settings are missing.
- [ ] Pin PyMuPDF, add `VISUALS_ENABLED` and `VISUAL_MAX_PDF_BYTES`, and
  implement `S3PdfPageRenderer` with bounded reads and an LRU page cache.
- [ ] Verify the rendered result starts with `data:image/jpeg;base64,` and the
  negative cases fail safely.

### Task 3: Extend the API contract without breaking fixtures

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api.py`

- [ ] Add failing API tests for rendered visual fields and renderer failure.
- [ ] Run the targeted tests and confirm the fields are absent.
- [ ] Inject the renderer into `create_app`, extend `VisualData`, and catch
  renderer errors while preserving the answer.
- [ ] Verify existing static `figure_id` and fixture behavior remain valid.

### Task 4: Document and verify live behavior

**Files:**
- Modify: `API.md`
- Modify: `API.ja.md`
- Modify: `README.md`
- Modify: `README.ja.md`
- Modify: `scripts/smoke-live.ps1`
- Modify: `PROJECT_CONTEXT.md`

- [ ] Document the optional visual fields and direct `<img src>` usage.
- [ ] Make live smoke assert a real HF-2000 JPEG/page/source response.
- [ ] Run the complete pytest suite and coverage gate.
- [ ] Run local/deep smoke plus live AWS smoke.
- [ ] Decode the live data URL, inspect the rendered page, and remove temporary
  inspection files.
- [ ] Run `git diff --check` and review the final diff for unrelated changes.
