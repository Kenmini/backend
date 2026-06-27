$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$environment = Save-ProcessEnvironment @(
    "APP_MODE", "ANSWER_PATH", "STORAGE_MODE", "DATABASE_PATH", "PUBLIC_DEMO"
)
Push-Location $root
try {
    $env:APP_MODE = "demo"
    $env:ANSWER_PATH = "advanced"
    $env:STORAGE_MODE = "sqlite"
    $env:DATABASE_PATH = "data/demo.db"
    $env:PUBLIC_DEMO = "false"
    & (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --reload --port 8000 --app-dir $root
    if ($LASTEXITCODE -ne 0) { throw "Demo server exited with an error" }
} finally {
    Restore-ProcessEnvironment $environment
    Pop-Location
}
