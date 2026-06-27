# Local Operations Runbook

All commands below run from the backend repository root in Windows PowerShell.
They use `.venv\Scripts\python.exe` directly, so PowerShell execution policy does
not affect Python activation.

## Before the demo

```powershell
pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest --cov=app --cov=config --cov=figures --cov-fail-under=85
.\scripts\render-charts.ps1
.\scripts\render-presentation-charts.ps1
.\scripts\smoke.ps1
.\scripts\smoke-deep.ps1
.\scripts\backup.ps1
```

For live AWS mode, also run:

```powershell
.\scripts\preflight.ps1
.\scripts\smoke-live.ps1
```

The preflight verifies account `465239007752`, region `us-east-1`, Knowledge
Base retrieval, Sonnet structured output, and Haiku text generation. It makes
model calls but never uploads or changes Knowledge Base documents.

The live smoke runner uses a `0.20` weak-retrieval cutoff and verifies a cited
Sonnet answer, a model-audited gap, gap persistence, and a Haiku onboarding
guide.

## Start modes

```powershell
.\scripts\run-live-advanced.ps1  # Sonnet /ask, Haiku /onboarding
.\scripts\run-live-easy.ps1      # managed retrieve_and_generate fallback
.\scripts\run-demo.ps1           # deterministic local fixtures, no AWS
```

Mode changes are explicit. An AWS error never silently switches the app to
fixture responses.

## Temporary public HTTPS access

Install Cloudflare's tunnel client once:

```powershell
winget install --id Cloudflare.cloudflared --exact
```

Then start the backend with the exact frontend origin. You must explicitly
choose `demo` or `live`; the launcher has no default mode.

```powershell
.\scripts\start-public-demo.ps1 -Mode demo -FrontendOrigin https://your-frontend.example
```

The launcher generates a temporary token, binds Uvicorn only to `127.0.0.1`,
publishes a random HTTPS Quick Tunnel URL, and runs public smoke tests before
remaining active. The frontend must send the displayed token in the
`X-Demo-Token` header. `/health` remains public; all other API endpoints require
the token. API documentation and OpenAPI routes are disabled in public mode.

Press `Ctrl+C` immediately after the session. This stops the backend and tunnel,
invalidates the random URL, and removes the token from the launcher process.
See [HOSTING.md](HOSTING.md) for the security model and alternatives.

## Stage contingency

1. Use live advanced mode after a successful preflight and smoke check.
2. If Converse is unavailable but the managed RAG path works, use live easy.
3. If AWS or the Knowledge Base is unavailable, announce demo mode and run the
   deterministic local fixtures.
4. Keep `/health` for liveness and `/ready` for local dependency state.

## Backup and restore

`backup.ps1` creates an integrity-checked SQLite snapshot under `backups/` and
keeps the newest ten snapshots.

```powershell
.\scripts\backup.ps1
.\scripts\restore.ps1 -Backup .\backups\app-YYYYMMDDTHHMMSSZ.db -ConfirmRestore
.\scripts\smoke.ps1
```

Restore verifies the selected snapshot and creates a timestamped pre-restore
safety copy beside the active database before overwriting it. Databases,
backups, and generated charts remain local and are never committed.

## Expected failures

- Empty retrieval results: upload lab documents and run Sync in Bedrock.
- Wrong account or region: rerun `aws configure`; the region must be
  `us-east-1`.
- Sonnet structured-output warm-up delay: wait for `preflight.ps1` to finish
  before going on stage.
- Live model failure: use the next explicit mode in the contingency sequence.
- Public smoke failure: do not share the URL; fix the reported token, CORS, or
  endpoint failure first.
