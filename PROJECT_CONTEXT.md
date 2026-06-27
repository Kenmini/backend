# PROJECT_CONTEXT.md — Single Source of Truth

> **Read this file first** at the start of any work session.
> **Append a dated changelog entry** at the end of any work session.
> This is the living memory of the project. Keep it accurate.

---

## 1. Product

**Name:** 研究室の暗黙知を継承するAIナレッジエージェント
(Lab Tacit-Knowledge Inheritance AI Agent)

A student-facing **agentic RAG assistant** built on **Amazon Bedrock**. It
absorbs a research lab's scattered knowledge — past papers, experiment records,
meeting notes, Slack logs, equipment manuals, facility rules — and answers new
students' questions in chat, grounded only in those documents.

**Target users:** New graduate students (M1, D1) and their supervising
professors.

**Problem:** Lab know-how is oral and person-dependent. It leaves when people
graduate. New students relearn from zero; professors repeat the same onboarding
every year. This system preserves that knowledge persistently and, crucially,
**detects what the lab has never written down**.

**Event:** UMP-JUST Agentic AI Hackathon, June 27–28 2026, University of Tokyo.
Theme: *social implementation of agentic AI*. **Judges weigh responsibility,
governance, and ethics heavily**, not just technical novelty. Build platform is
AWS Bedrock (AWS Kiro and Azure OpenAI also available).

---

## 2. AWS Resources (identifiers, NOT secrets)

| Item | Value |
|------|-------|
| Account ID | `465239007752` |
| **Region** | **`us-east-1`** (N. Virginia — *NOT* Tokyo) |
| Knowledge Base ID | `AJVVEPYMSH` |
| Embeddings | Titan Text Embeddings v2 (managed by the KB, never called directly) |
| Vector store | Amazon Aurora (managed by the KB) |
| Data source | S3 source named **`bedrock-docs`**. Must be **Synced** after files are uploaded. |

**Models**

| Role | Model ID |
|------|----------|
| Smart (main answers) | `us.anthropic.claude-sonnet-4-6` |
| Fast (onboarding) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

### Known gotchas (these cost real time — read them)

- **Everything is `us-east-1`.** Any `ap-northeast-1` (Tokyo) reference is a bug.
- **Sonnet 4.6 is an INFERENCE_PROFILE model.**
  - For the **converse** API use modelId `us.anthropic.claude-sonnet-4-6`.
  - For **retrieve_and_generate** use the modelArn
    `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6`.
  - If you get a validation error about **on-demand throughput**, switch the
    modelArn to the inference-profile ARN:
    `arn:aws:bedrock:us-east-1:465239007752:inference-profile/us.anthropic.claude-sonnet-4-6`
    (set `MODEL_SMART_ARN` in `.env` to override — no code change needed).
- **The KB returns empty results** until documents are uploaded to the S3
  source **AND** the *Sync* button is pressed in the console. **This is the
  current blocker.** Until then, every `/ask` correctly reports a knowledge gap
  (top score 0 < threshold), which is honest behaviour, not a failure.

---

## 3. Credential Handling Rules (do not violate)

- **NEVER** hardcode AWS access/secret keys in any source file.
- **NEVER** write real secret values into any committed file.
- Credentials are supplied at runtime, in this priority order:
  1. Standard AWS credential chain via `aws configure` (**preferred**).
  2. A local `.env` file (gitignored) loaded at startup by `python-dotenv`.
- `.env.example` is committed with **placeholder values only**.
- `.gitignore` excludes `.env`, `*.csv`, `*.txt` (credential dumps),
  `__pycache__`, and the runtime `gaps.json`. (`requirements.txt` is explicitly
  un-ignored so it stays committed.)
- boto3 picks up credentials from the environment automatically; the client
  code contains **no keys**.

---

## 4. API Contract (build to this exactly)

Merged from two team proposals: a **visual/stateful frontend** design and a
**trust/governance** layer. The frontend may ignore fields it does not yet
render, so all fields are always included.

### `POST /ask`
```json
// request
{
  "message": "輝度つまみはどこですか？",
  "session_id": "session_98765",
  "current_state": { "active_figure_id": "panel_01" }
}
// response
{
  "answer_text": "照射系を調整するには、パネル右上の輝度つまみを時計回りに回します。",
  "next_step_hint": "次に、対物レンズのフォーカスを確認してください。",
  "visual_data": { "figure_id": "panel_01", "highlight_item": "輝度つまみ" },
  "citations": [ { "source": "顕微鏡マニュアル.pdf", "snippet": "..." } ],
  "confidence": 0.82,
  "is_gap": false
}
```

### Other endpoints
- `GET  /gaps` → `{ "gaps": [ { "question": str, "count": int, "first_seen": str } ] }`
- `POST /onboarding` → body `{ "role": "M1"|"D1", "field": str? }` → `{ "guide": str }`
- `GET  /faq` → `{ "items": [ { "q": str, "a": str } ] }`
- `POST /feedback` → body `{ "session_id": str, "message": str, "rating": "up"|"down", "note": str? }` → `{ "ok": true }`
- `GET  /health` → `{ "status": "ok" }`

Full reference with examples: see `API.md`.

---

## 5. Signature Agentic Feature — Knowledge-Gap Detection

**This is the differentiator.** When answering, the backend reads the **top
retrieval similarity score**. If it is below the calibrated threshold
(`GAP_THRESHOLD`, currently `0.79`):

1. The answer **honestly states** the topic is not yet documented.
2. `is_gap` is set to `true`.
3. The question is **logged to a gaps store** (`gaps.json`).

`GET /gaps` exposes these for the professor to review.

**Why it matters:** it turns a passive chatbot into an agent that detects what
the lab has *never written down* and surfaces it for capture. This is the
governance / anti-hallucination story the judges want, and it demos in seconds.

### Two implementation paths

**EASY path (explicit fallback).** Uses `bedrock-agent-runtime`:
- First `retrieve` to get the top similarity score.
- If below threshold → return the honest "not documented" message, `is_gap=true`,
  **skip generation entirely** (never hallucinate past recorded knowledge).
- Otherwise `retrieve_and_generate` for a grounded answer + citations.

**ADVANCED path (default).** Calls `retrieve` for chunks + scores, builds a
context block, then `bedrock-runtime.converse` with the Japanese system prompt,
the latest 10 session turns, and a JSON response schema. Sonnet handles `/ask`;
Haiku handles `/onboarding`. Citations and confidence remain retrieval-derived.

### visual_data sourcing (MVP)
**No figure auto-tagging.** `figures.py` holds a small set of hand-prepared
figures, each with a fixed list of named hotspots. The backend constrains
`highlight_item` to that known list (MVP: keyword match against the answer text).
Looks identical on stage, fraction of the effort.

---

## 6. Files

```
backend/                  (this repo root)
  app/api.py         FastAPI app factory, schemas, routes, readiness.
  app/services.py    Ask/onboarding orchestration and safe fallbacks.
  app/providers.py   Bedrock and deterministic fixture providers.
  app/repositories.py SQLite/memory stores, migrations, backup/restore.
  app/preflight.py   Live AWS identity, retrieval, and model checks.
  config.py          Validated env configuration and compatibility aliases.
  prompts.py         Japanese system and RAG prompt templates.
  figures.py         Static figure/hotspot constraints.
  fixtures/          Reviewed local demo responses.
  scripts/           Windows launch, smoke, chart, preflight, recovery tools.
  tests/             Unit and full endpoint contract tests.
  docs/              Architecture sources and operations runbook.
  main.py            Thin Uvicorn entrypoint.
```

The **Japanese system prompt** lives in `prompts.py` (`SYSTEM_PROMPT`).

---

## Current status

- ✅ Modular FastAPI backend; **ADVANCED path is the documented default**.
- ✅ `GET /health` returns `{"status":"ok"}`; app starts with `uvicorn main:app`.
- ✅ `POST /ask` uses Sonnet Converse, structured output, citations, next-step
  hints, and bounded SQLite session history.
- ✅ `/onboarding` routes through Haiku; `/faq` remains static and deterministic.
- ✅ SQLite stores gaps, feedback, and interactions; memory mode is explicit.
- ✅ `/ready`, fixture demo mode, JSON logs, backup/restore, AWS preflight,
  Windows smoke tests, and rendered architecture charts implemented.
- ✅ Pytest covers every endpoint and enforces at least 85% application coverage.
- ✅ Knowledge Base retrieval currently returns synced documents.
- ✅ Live preflight verified account `465239007752`, `us-east-1`, five retrieval
  results, Sonnet structured output, and Haiku Converse.
- ✅ Live endpoint smoke verified a cited answer, a `0.79`-threshold gap, gap
  persistence, and onboarding generation.

---

## Decisions log

- **Advanced is the default; easy is an explicit fallback.** Sonnet Converse
  provides schema-constrained answers, history, and next-step hints. The managed
  easy path remains available for stage contingency without automatic failover.
- **Gap detection is the signature feature.** The hackathon is judged on
  responsibility/governance/ethics. A RAG bot that *admits what it doesn't know*
  and *captures the gap for humans* is a stronger story than raw answer quality,
  and it demos in seconds. We even run a real `retrieve` on the easy path (not
  just a heuristic) so the gap signal is genuine.
- **Gap-case skips generation.** When the top score is below threshold we do
  **not** call the generator at all — we return the honest message. This makes
  hallucination structurally impossible in the gap case, which is the cleanest
  governance claim.
- **Merged API contract.** The contract combines a visual/stateful frontend
  proposal (`visual_data`, `next_step_hint`, `current_state`) with a
  trust/governance proposal (`citations`, `confidence`, `is_gap`). All fields
  ship even if a given frontend ignores some — agreed so frontend and backend
  can build in parallel without blocking each other.
- **Figures are hand-prepared, not auto-tagged.** Auto-tagging figures from
  PDFs is out of scope for the MVP; a fixed hotspot map looks identical on stage.
- **Region pinned in config.** All boto3 clients use `config.REGION`
  (`us-east-1`) so a stray default region can't silently break retrieval.
- **LLMs are routed by endpoint.** Sonnet handles grounded questions; Haiku
  handles onboarding. Static FAQ responses make no model call.
- **Demo fallback is explicit.** `APP_MODE=demo` uses reviewed local fixtures;
  live AWS failures never silently produce simulated answers.
- **SQLite is the local durable store.** It requires no service installation,
  supports online verified backups, and can be replaced by memory mode explicitly.

---

## Open questions

- **Figure sourcing path.** Keep the static hotspot map, or invest in real
  figure auto-tagging at ingestion? (MVP = static.)
- **Gap threshold tuning.** `0.79` separates the committed live smoke queries,
  but retrieval scores overlap for some unrelated questions. Keep measuring
  known-answer and known-gap sets before claiming universal calibration.
- **Streaming.** Add `converse_stream` for a typing effect in the demo? (Stretch.)
- **Bedrock Guardrails.** Attach a Guardrail for an extra governance layer
  (PII redaction, denied topics)? Strong fit for the judging criteria. (Stretch.)

---

## Extension points (where future work slots in)

The code is kept comment-light on purpose; this is the single place that records
the planned extensions and exactly where each one goes. Refer here instead of
hunting for inline TODOs.

| Planned work | Where it slots in |
|--------------|-------------------|
| Advanced answer path | `app.providers.BedrockAnswerProvider`; active with `ANSWER_PATH=advanced`. |
| Per-session conversation history | `app.repositories` stores and bounds the latest 10 interactions. |
| `next_step_hint` generation | Sonnet structured output in `app.providers`. |
| Real figure auto-tagging | Replace the static map in `figures.py` and have the model return `highlight_item` as structured output. |
| Streaming (typing effect) | Add a streaming provider method and route in `app/api.py`. |
| Bedrock Guardrails | Add `guardrailConfig` to Converse calls in `app/providers.py`. |
| Cloud persistence | Add a repository implementation without changing routes or services. |

---

## Changelog

### 2026-06-27 — Initial scaffold
- Created the full backend per spec: `config.py`, `bedrock.py`, `prompts.py`,
  `gaps.py`, `figures.py`, `main.py`, `requirements.txt`, `.env.example`,
  `.gitignore`, `README.md`, `API.md`, and this `PROJECT_CONTEXT.md`.
- EASY path active; ADVANCED path implemented behind `ANSWER_PATH=advanced`.
- Gap detection wired end-to-end (real `retrieve` for the score, honest message
  + `gaps.json` logging on gap).
- Verified the app imports and `GET /health` returns `{"status":"ok"}` via
  FastAPI TestClient (no AWS calls needed for that check).
- **Next step:** upload lab documents to the `bedrock-docs` S3 source and press
  **Sync** in the Bedrock console, then exercise `POST /ask` against real data
  and calibrate `GAP_THRESHOLD`.

### 2026-06-27 — Trimmed inline comments
- Reduced verbose per-line/per-function comments across all modules to a sparse,
  natural style. Planned extensions now live in the **Extension points** section
  above (single source) rather than scattered inline TODOs.
- Behaviour unchanged; re-verified `GET /health` and the non-AWS endpoints.

### 2026-06-27 — Backend hardening, LLM routing, and local operations
- Replaced the flat runtime with API, service, provider, and repository
  boundaries while keeping the public response contracts compatible.
- Made advanced retrieval + Sonnet Converse the documented `/ask` default,
  added schema-constrained answers, next-step hints, and bounded history.
- Routed `/onboarding` through Haiku and kept `/faq` model-free.
- Added SQLite persistence, memory mode, legacy gap import, verified backups,
  guarded restores, request IDs, JSON logs, readiness, and explicit demo mode.
- Added endpoint/unit coverage, an 85% coverage gate, Windows smoke/preflight
  scripts, Mermaid architecture sources, and local PNG/SVG chart generation.
- Live AWS verification passed for retrieval, Sonnet structured output, Haiku,
  a cited `/ask`, a calibrated gap, and `/onboarding`; default threshold moved
  from the initial `0.4` guess to the provisional `0.79` hackathon value.
