$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$environment = Save-ProcessEnvironment @("PYTHONIOENCODING")
Push-Location $root
try {
    $env:PYTHONIOENCODING = "utf-8"
    & ".venv\Scripts\python.exe" ".\scripts\deep_smoke.py"
    if ($LASTEXITCODE -ne 0) { throw "Deep smoke test failed" }
} finally {
    Restore-ProcessEnvironment $environment
    Pop-Location
}
