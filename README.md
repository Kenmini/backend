# Lab Tacit-Knowledge AI Agent — Backend

研究室の暗黙知を継承するAIナレッジエージェント — backend service.

A retrieval-augmented (RAG) agent on **Amazon Bedrock** that answers new
students' questions from a research lab's own documents, **cites its sources**,
and — the signature feature — **detects knowledge gaps**: when the lab has no
documented answer, it says so honestly and logs the question for a professor to
review instead of guessing.

> New here? Read **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** first — it is the
> single source of truth for the project's state, decisions, and open questions.
> For the HTTP contract, see **[API.md](API.md)**.

---

## Quick start

You need **Python 3.10+** and AWS access to the Bedrock resources (see below).

### 1. Clone and enter the repo
```bash
git clone git@github.com:Kenmini/backend.git
cd backend
```

### 2. Create a virtual environment and install deps

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 3. Provide AWS credentials (pick ONE)

**Option A — `aws configure` (preferred).** boto3 picks these up automatically.
```bash
aws configure
# AWS Access Key ID:     <your key>
# AWS Secret Access Key: <your secret>
# Default region name:   us-east-1      <-- IMPORTANT: us-east-1, not Tokyo
# Default output format:  json
```

**Option B — local `.env` file.** Copy the example and fill it in. `.env` is
gitignored and must never be committed.
```bash
cp .env.example .env        # macOS/Linux
copy .env.example .env      # Windows
```
Then edit `.env` and set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

> Credentials are **never** stored in source. They come only from the AWS
> credential chain or `.env` at runtime.

### 4. Run the server
```bash
uvicorn main:app --reload --port 8000
```

![Server running](images/server-running.png)

### 5. Verify it's up
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```
Interactive API docs (auto-generated): <http://localhost:8000/docs>

---

## Try it

```bash
# Ask a question (returns the full contract: answer, citations, confidence,
# is_gap, visual_data, next_step_hint)
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message":"輝度つまみはどこですか？","session_id":"s1","current_state":{"active_figure_id":"panel_01"}}'

# Review detected knowledge gaps (for professors)
curl http://localhost:8000/gaps
```

> **Expected before the Knowledge Base is synced:** every `/ask` returns
> `is_gap: true` with an honest "not documented yet" message. That is correct —
> the KB returns nothing until documents are uploaded to the `bedrock-docs` S3
> source **and** the **Sync** button is pressed in the Bedrock console. See
> *Current status* in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## AWS resources (identifiers, not secrets)

| Item | Value |
|------|-------|
| Region | **us-east-1** (N. Virginia) |
| Knowledge Base ID | `AJVVEPYMSH` |
| Data source (S3) | `bedrock-docs` (must be **Synced** after uploads) |
| Smart model | `us.anthropic.claude-sonnet-4-6` |
| Fast model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

You need a role/user with Bedrock permissions: `bedrock:Retrieve`,
`bedrock:RetrieveAndGenerate`, and `bedrock:InvokeModel` (plus `Converse` for
the advanced path), and model access granted for the two models in us-east-1.

---

## Configuration

All config lives in [`config.py`](config.py) and every value can be overridden
with an environment variable (see [`.env.example`](.env.example)):

| Env var | Default | Meaning |
|---------|---------|---------|
| `AWS_REGION` | `us-east-1` | AWS region for all clients |
| `KB_ID` | `AJVVEPYMSH` | Bedrock Knowledge Base id |
| `MODEL_SMART` | `us.anthropic.claude-sonnet-4-6` | Main answer model |
| `MODEL_FAST` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | FAQ/bulk model |
| `MODEL_SMART_ARN` | foundation-model ARN | Model ARN for retrieve_and_generate |
| `GAP_THRESHOLD` | `0.4` | Below this top-score → knowledge gap |
| `ANSWER_PATH` | `easy` | `easy` (retrieve_and_generate) or `advanced` (retrieve+converse) |
| `NUM_RESULTS` | `5` | Chunks to retrieve |

### Easy vs. advanced answer path
- **easy** (default): one managed `retrieve_and_generate` call after a quick
  `retrieve` for the gap score. Least code.
- **advanced**: `retrieve` + `converse` with a custom Japanese system prompt and
  per-session history. Set `ANSWER_PATH=advanced` to enable.

---

## Troubleshooting

- **Validation error about on-demand throughput** on `/ask`: Sonnet 4.6 is an
  inference-profile model. Set in `.env`:
  ```
  MODEL_SMART_ARN=arn:aws:bedrock:us-east-1:465239007752:inference-profile/us.anthropic.claude-sonnet-4-6
  ```
- **Everything returns `is_gap: true`:** the KB isn't synced — upload to the
  `bedrock-docs` S3 source and press **Sync**.
- **`AccessDeniedException` / `UnrecognizedClientException`:** credentials or
  region wrong. Confirm `aws sts get-caller-identity` works and region is
  `us-east-1`. Model access must be granted in the Bedrock console.
- **`ResourceNotFoundException`:** wrong `KB_ID`, or you're pointed at the wrong
  region (Tokyo instead of N. Virginia).

---

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, routes, Pydantic models |
| `bedrock.py` | All Bedrock calls; `answer()` dispatcher (easy/advanced) |
| `config.py` | Central config, env overrides, no secrets |
| `prompts.py` | Japanese system prompt, RAG/onboarding templates, gap message |
| `gaps.py` | Knowledge-gap store (`gaps.json`) |
| `figures.py` | Demo figures + hotspots that constrain `visual_data` |
| `API.md` | Full HTTP API reference |
| `PROJECT_CONTEXT.md` | Living source of truth — read first, update last |
