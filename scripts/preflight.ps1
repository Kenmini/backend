$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    $env:APP_MODE = "live"
    & ".venv\Scripts\python.exe" -m app.preflight
} finally {
    Pop-Location
}
