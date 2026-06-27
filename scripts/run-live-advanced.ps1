$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$environment = Save-ProcessEnvironment @(
    "APP_MODE", "ANSWER_PATH", "STORAGE_MODE", "GAP_THRESHOLD", "PUBLIC_DEMO"
)
Push-Location $root
try {
    $env:APP_MODE = "live"
    $env:ANSWER_PATH = "advanced"
    $env:STORAGE_MODE = "sqlite"
    $env:GAP_THRESHOLD = "0.20"
    $env:PUBLIC_DEMO = "false"
    & (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn main:app --reload --port 8000 --app-dir $root
    if ($LASTEXITCODE -ne 0) { throw "Live advanced server exited with an error" }
} finally {
    Restore-ProcessEnvironment $environment
    Pop-Location
}
