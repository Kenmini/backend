# Lab AI Knowledge Agent — Backend

An AI assistant that answers questions about the lab using uploaded documents (RAG on Amazon Bedrock). If it doesn't know the answer, it says so honestly and logs the question for a professor to review — instead of making something up.

---

## For the Frontend Team

You don't need to understand the Python code at all. Just run the server locally (steps below) and call the API. The full API contract is in [API.md](API.md).

Base URL: `http://localhost:8000`  
All requests and responses are JSON.  
Interactive API explorer (auto-generated): [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Setup (Windows)

### 1. Make sure you have Python installed
```powershell
python --version
# should be 3.10 or higher
```

### 2. Navigate to the backend folder and activate the virtual environment
```powershell
cd C:\path\to\umpjust\backend
.venv\Scripts\activate.bat
```

If `.venv` doesn't exist yet, create it first:
```powershell
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 3. Set up AWS credentials
Run this once — boto3 picks it up automatically after that.
```powershell
aws configure
# AWS Access Key ID:     <your key>
# AWS Secret Access Key: <your secret>
# Default region name:   us-east-1     <-- must be us-east-1, not Tokyo
# Default output format: json
```

### 4. Start the server
```powershell
uvicorn main:app --reload --port 8000
```

![Server running](images/server-running.png)

### 5. Verify it's working
```powershell
curl http://localhost:8000/health
```

![Health check response](images/health-check.png)

You should see `{"status":"ok"}`. You're good to go.

For a deterministic demo without AWS, run:
```powershell
.\scripts\run-demo.ps1
```

Before using live Bedrock, verify the account, Knowledge Base, Sonnet, and
Haiku in one pass:
```powershell
.\scripts\preflight.ps1
```

### Live English/Japanese retrieval check

With the live server running on port `8000`, define this PowerShell helper:

```powershell
function Ask-Backend {
    param([string]$Message, [string]$Session)

    $body = @{
        message = $Message
        session_id = $Session
    } | ConvertTo-Json

    Invoke-RestMethod `
        -Uri "http://localhost:8000/ask" `
        -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
}
```

Test all four language directions:

```powershell
# English question -> English document
Ask-Backend "What are Amazon Bedrock Guardrails used for?" "language-en-en"

# Japanese question -> English document
Ask-Backend "Amazon Bedrock Guardrailsの主な用途は何ですか？" "language-ja-en"

# English question -> Japanese document
Ask-Backend "How often should liquid nitrogen be replenished in the HF-2000 after the initial refill?" "language-en-ja"

# Japanese question -> Japanese document
Ask-Backend "HF-2000の液体窒素は最初の補充後どのくらいの間隔で補充しますか？" "language-ja-ja"
```

The expected liquid-nitrogen answer is: refill after 30 minutes, then every
3 hours. Live verification confirmed retrieval and answering in both
directions. The current prompt answers in the question's language, but the API
does not yet return an explicit translation notice, and occasional labels or
next-step hints can use the source language. Titan Text Embeddings V2 supports
English and Japanese, but AWS notes that cross-language retrieval can be
suboptimal. See the [AWS Titan Embeddings documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html).

## Development and demo checks

```powershell
pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest --cov=app --cov=config --cov=figures --cov-fail-under=85
.\scripts\smoke.ps1
.\scripts\render-charts.ps1
```

The architecture chart sources are committed under `docs/architecture/`.
Generated PNG and SVG files are written to the local, gitignored
`images/charts/` folder. See [docs/OPERATIONS.md](docs/OPERATIONS.md) for mode
switching, backup, restore, and stage contingencies.

For a temporary hackathon HTTPS URL, install `cloudflared` and run the guarded
launcher with the deployed frontend's exact origin:

```powershell
winget install --id Cloudflare.cloudflared --exact
.\scripts\start-public-demo.ps1 -Mode demo -FrontendOrigin https://your-frontend.example
```

The frontend must send the printed `X-Demo-Token`. Stop the launcher with
`Ctrl+C` after the session. See [docs/HOSTING.md](docs/HOSTING.md) before using
the public profile.

Presentation-ready English/Japanese diagrams in light and dark themes can be
generated with `scripts\render-presentation-charts.ps1`.

---

## API Endpoints

### `POST /ask` — Ask the AI a question

This is the main endpoint. Send a question, get an answer with citations.

**Request:**
```json
{
  "message": "輝度つまみはどこですか？",
  "session_id": "session_123",
  "current_state": { "active_figure_id": "panel_01" }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `message` | yes | The question (any language, Japanese expected) |
| `session_id` | no | Any string to identify the session |
| `current_state.active_figure_id` | no | Which figure the user is viewing (`panel_01` by default) |

**Response (answer found):**
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

**Response (answer not found — knowledge gap):**
```json
{
  "answer_text": "ご質問の内容は、まだ研究室の資料に記録されていないようです。この質問は記録しましたので、先生が後で確認できます。",
  "next_step_hint": null,
  "visual_data": { "figure_id": "panel_01", "highlight_item": null },
  "citations": [],
  "confidence": 0.0,
  "is_gap": true
}
```

| Response Field | Description |
|----------------|-------------|
| `answer_text` | The answer, or an honest "I don't know" if undocumented |
| `visual_data.highlight_item` | A hotspot name to highlight on the figure (or `null`) |
| `citations` | Source documents the answer is based on |
| `confidence` | Retrieval score for supported answers; `0.0` for knowledge gaps |
| `is_gap` | `true` means no documented answer — question is logged for professors |

**Valid figure IDs and hotspot names for `visual_data`:**

| `figure_id` | Valid `highlight_item` values |
|-------------|-------------------------------|
| `panel_01` | 輝度つまみ, 対物レンズ, フォーカスノブ, ステージ, 電源スイッチ |
| `microscope_overview` | 接眼レンズ, 対物レンズ, ステージ, 光源, 粗動ハンドル, 微動ハンドル |
| `control_panel` | 電源スイッチ, 輝度つまみ, シャッターボタン, 緊急停止ボタン |

---

### `GET /gaps` — View unanswered questions (for professors)

Returns all questions the AI couldn't answer, sorted by how often they were asked.

**Response:**
```json
{
  "gaps": [
    { "question": "懇親会の予算は？", "count": 3, "first_seen": "2026-06-27T09:30:00+00:00" },
    { "question": "古い液体窒素タンクの場所は？", "count": 1, "first_seen": "2026-06-27T10:05:00+00:00" }
  ]
}
```

---

### `POST /onboarding` — Generate an onboarding guide

Generates a role-specific onboarding guide from lab documents.

**Request:**
```json
{ "role": "M1", "field": "光学" }
```

| Field | Required | Description |
|-------|----------|-------------|
| `role` | yes | `"M1"` or `"D1"` |
| `field` | no | Research field to tailor the guide |

**Response:**
```json
{ "guide": "M1向けオンボーディングガイド\n\n1. 最初の1週間でやるべきこと…" }
```

---

### `GET /faq` — Get frequently asked questions

**Response:**
```json
{
  "items": [
    { "q": "研究室のコアタイムは何時ですか？", "a": "コアタイムは研究室の資料を確認してください。" }
  ]
}
```

---

### `POST /feedback` — Submit a thumbs up/down on an answer

**Request:**
```json
{
  "session_id": "session_123",
  "message": "輝度つまみはどこですか？",
  "rating": "up",
  "note": "分かりやすかった"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `session_id` | yes | Session ID from the `/ask` call |
| `message` | yes | The question being rated |
| `rating` | yes | `"up"` or `"down"` |
| `note` | no | Optional comment |

**Response:**
```json
{ "ok": true }
```

---

### `GET /health` — Check if the server is running

```json
{ "status": "ok" }
```

No AWS calls — safe to poll at any frequency.

### `GET /ready` — Check local dependencies

```json
{"status":"ready","mode":"live","database":"ok","provider":"configured"}
```

This validates local database access and provider configuration without making
a paid AWS call.

---

## Troubleshooting

**Everything returns `is_gap: true`**  
Confirm that the required answer is present in the indexed documents, then run
`scripts\preflight.ps1`. The current `bedrock-docs` data source is synced; a
genuine unsupported question intentionally returns the gap response.

**Preflight says the Aurora database is resuming**

The Knowledge Base vector store can auto-pause while idle. Wait a few seconds
and rerun `scripts\preflight.ps1`.

**`AccessDeniedException` or credentials error**  
Run `aws sts get-caller-identity` to verify your credentials work. Make sure the region is `us-east-1`.

**Validation error about on-demand throughput on `/ask`**  
Add this to a `.env` file in the backend folder:
```
MODEL_SMART_ARN=arn:aws:bedrock:us-east-1:465239007752:inference-profile/us.anthropic.claude-sonnet-4-6
```

**`curl` in PowerShell shows a security warning**  
That's Windows aliasing `curl` to `Invoke-WebRequest`. Either type `A` to continue, or use the real curl by running:
```powershell
curl.exe http://localhost:8000/health
```

---

## AWS Resources

| Item | Value |
|------|-------|
| Region | `us-east-1` (N. Virginia) |
| Knowledge Base ID | `AJVVEPYMSH` |
| Data source | `bedrock-docs` (`N4SIKZJMBR`) |
| S3 bucket | `bedrock-docs-ttanaka-202606` |
| Main model | `us.anthropic.claude-sonnet-4-6` |
| Fast model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

---

## Project Files

| File | What it does |
|------|--------------|
| `main.py` | Thin Uvicorn entrypoint |
| `app/api.py` | FastAPI app factory, routes, and validation |
| `app/providers.py` | Bedrock Converse and deterministic fixture providers |
| `app/repositories.py` | SQLite and memory persistence plus backup/restore |
| `app/services.py` | Answer, history, gap, and fallback coordination |
| `config.py` | Validated configuration and compatibility aliases |
| `prompts.py` | Japanese system prompts and templates |
| `figures.py` | Figure definitions and hotspot lists |
| `scripts/` | Windows launch, smoke, preflight, chart, and recovery tools |
| `API.md` | Full API reference |
