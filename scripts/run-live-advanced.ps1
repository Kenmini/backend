$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:APP_MODE = "live"
$env:ANSWER_PATH = "advanced"
$env:STORAGE_MODE = "sqlite"
$env:GAP_THRESHOLD = "0.79"
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --reload --port 8000 --app-dir $root
