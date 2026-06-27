$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:APP_MODE = "live"
$env:ANSWER_PATH = "easy"
$env:STORAGE_MODE = "sqlite"
$env:GAP_THRESHOLD = "0.20"
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --reload --port 8000 --app-dir $root
