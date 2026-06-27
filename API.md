# API Reference — Lab Tacit-Knowledge AI Agent

Base URL (local): `http://localhost:8000`
Content type: `application/json` for all request bodies.
CORS is open (`*`) for the hackathon.

Interactive, always-up-to-date docs are also served at `/docs` (Swagger) and
`/redoc` when the server is running.

This document is the contract. A frontend dev can build against it without
reading the Python.

---

## Conventions

- JSON responses explicitly declare UTF-8 (`application/json; charset=utf-8`)
  for compatibility with Windows PowerShell's `Invoke-WebRequest`/`curl` alias.
- The frontend may safely **ignore fields it does not render** — every field is
  always present so backend and frontend can evolve independently.
- Timestamps are ISO-8601 UTC strings (e.g. `2026-06-27T09:30:00+00:00`).

---

## `POST /ask`

The main RAG endpoint. Answers a question from lab documents, returns citations,
a confidence score, optional visual highlight data, and the knowledge-gap flag.

### Request body
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's question (any language; Japanese expected). |
| `session_id` | string | no | Opaque session id. Reserved for per-session history on the advanced path. |
| `current_state` | object | no | Frontend UI state. Currently read for `active_figure_id`. |
| `current_state.active_figure_id` | string | no | Which figure the user is looking at; constrains `visual_data`. Falls back to `panel_01`. |

```json
{
  "message": "輝度つまみはどこですか？",
  "session_id": "session_98765",
  "current_state": { "active_figure_id": "panel_01" }
}
```

### Response body
| Field | Type | Description |
|-------|------|-------------|
| `answer_text` | string | The grounded answer, or an honest "not documented yet" message when `is_gap` is true. |
| `next_step_hint` | string \| null | Suggested next action from the advanced path; `null` on the easy or gap path. |
| `visual_data` | object \| null | Which figure/hotspot to highlight. |
| `visual_data.figure_id` | string \| null | The active figure id (echoes the request or the default). |
| `visual_data.highlight_item` | string \| null | A hotspot name from that figure's known list, or `null` if none matched. |
| `citations` | array | Source passages the answer is based on. Empty when `is_gap` is true. |
| `citations[].source` | string | Source document name (e.g. file name). |
| `citations[].snippet` | string | Short excerpt from the source (≤300 chars). |
| `confidence` | number | Top retrieval score for a supported answer; `0.0` for a gap. |
| `is_gap` | boolean | **Signature feature.** `true` when no documented answer exists; the question is logged to `/gaps`. |

```json
{
  "answer_text": "照射系を調整するには、パネル右上の輝度つまみを時計回りに回します。",
  "next_step_hint": "次に、対物レンズのフォーカスを確認してください。",
  "visual_data": { "figure_id": "panel_01", "highlight_item": "輝度つまみ" },
  "citations": [
    { "source": "顕微鏡マニュアル.pdf", "snippet": "輝度つまみはパネル右上にあり…" }
  ],
  "confidence": 0.82,
  "is_gap": false
}
```

### Knowledge-gap response (the signature behaviour)
The backend declares a gap when the top retrieval score is below
`GAP_THRESHOLD` (default `0.20`) or when Sonnet determines that higher-scoring
chunks do not directly support the answer. Low-score gaps skip generation.
Model-rejected gaps discard the draft answer and citations. Both paths return
the honest gap message, set `is_gap: true`, set `confidence: 0.0`, and log the
question for professors.

```json
{
  "answer_text": "ご質問の内容は、まだ研究室の資料に記録されていないようです。この質問は記録しましたので、先生が後で確認できます。お急ぎの場合は、先輩や先生に直接確認することをおすすめします。",
  "next_step_hint": null,
  "visual_data": { "figure_id": "panel_01", "highlight_item": null },
  "citations": [],
  "confidence": 0.0,
  "is_gap": true
}
```

### Known figure ids and hotspots
`highlight_item` is always one of the active figure's known hotspots (or null):

| `figure_id` | valid `highlight_item` values |
|-------------|-------------------------------|
| `panel_01` | 輝度つまみ, 対物レンズ, フォーカスノブ, ステージ, 電源スイッチ |
| `microscope_overview` | 接眼レンズ, 対物レンズ, ステージ, 光源, 粗動ハンドル, 微動ハンドル |
| `control_panel` | 電源スイッチ, 輝度つまみ, シャッターボタン, 緊急停止ボタン |

---

## `GET /gaps`

List the knowledge gaps detected so far, **most-asked first**. For the
professor's review dashboard.

### Response body
| Field | Type | Description |
|-------|------|-------------|
| `gaps` | array | Detected gaps. |
| `gaps[].question` | string | The question that had no documented answer. |
| `gaps[].count` | integer | How many times it has been asked (deduped by exact text). |
| `gaps[].first_seen` | string | ISO-8601 UTC timestamp of the first occurrence. |

```json
{
  "gaps": [
    { "question": "懇親会の予算は？", "count": 3, "first_seen": "2026-06-27T09:30:00+00:00" },
    { "question": "古い液体窒素タンクの場所は？", "count": 1, "first_seen": "2026-06-27T10:05:00+00:00" }
  ]
}
```

---

## `POST /onboarding`

Generate a role-specific onboarding guide, grounded in lab documents.

### Request body
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | `"M1"` or `"D1"`. |
| `field` | string | no | Research field, used to tailor the guide. |

```json
{ "role": "M1", "field": "光学" }
```

### Response body
| Field | Type | Description |
|-------|------|-------------|
| `guide` | string | A generated onboarding guide (Japanese), based on lab material. |

```json
{ "guide": "M1向けオンボーディングガイド\n\n1. 最初の1週間でやるべきこと…" }
```

---

## `GET /faq`

Return frequently asked questions and answers.

### Response body
| Field | Type | Description |
|-------|------|-------------|
| `items` | array | FAQ entries. |
| `items[].q` | string | Question. |
| `items[].a` | string | Answer. |

```json
{
  "items": [
    { "q": "研究室のコアタイムは何時ですか？", "a": "コアタイムは研究室の資料を確認してください。" }
  ]
}
```

---

## `POST /feedback`

Record a thumbs up/down on an answer.

### Request body
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | Session the feedback belongs to. |
| `message` | string | yes | The question/answer being rated. |
| `rating` | string | yes | `"up"` or `"down"`. |
| `note` | string | no | Optional free-text comment. |

```json
{ "session_id": "session_98765", "message": "輝度つまみはどこですか？", "rating": "up", "note": "分かりやすかった" }
```

### Response body
| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Always `true` on success. |

```json
{ "ok": true }
```

---

## `GET /health`

Liveness check. No AWS calls — safe to poll.

### Response body
```json
{ "status": "ok" }
```

---

## `GET /ready`

Local readiness check. It verifies repository access and provider configuration
without invoking an LLM.

```json
{
  "status": "ready",
  "mode": "live",
  "database": "ok",
  "provider": "configured"
}
```

`status` becomes `degraded` when either dependency reports an error.

---

## Errors

- Validation errors (bad/missing fields) return **HTTP 422** with FastAPI's
  standard error body.
- If Bedrock is unreachable (KB not synced, wrong region, missing model access),
  `/ask` and `/onboarding` still return **HTTP 200** with a safe fallback
  message so the demo stays up — check `is_gap` / `answer_text` rather than
  relying on a non-200 status.
- `/feedback` returns **HTTP 503** if feedback cannot be persisted, and `/gaps`
  returns **HTTP 503** if stored gaps cannot be read.
- Unknown figure IDs, blank bounded strings, unsupported roles, and unsupported
  ratings return **HTTP 422**.
