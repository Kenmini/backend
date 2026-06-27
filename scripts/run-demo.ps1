$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:APP_MODE = "demo"
$env:ANSWER_PATH = "advanced"
$env:STORAGE_MODE = "sqlite"
$env:DATABASE_PATH = "data/demo.db"
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --reload --port 8000 --app-dir $root
