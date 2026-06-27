$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    $env:PYTHONIOENCODING = "utf-8"
    & ".venv\Scripts\python.exe" ".\scripts\deep_smoke.py"
    if ($LASTEXITCODE -ne 0) { throw "Deep smoke test failed" }
} finally {
    Pop-Location
}
