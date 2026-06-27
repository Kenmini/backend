$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$environment = Save-ProcessEnvironment @("APP_MODE", "PUBLIC_DEMO")
Push-Location $root
try {
    $env:APP_MODE = "live"
    $env:PUBLIC_DEMO = "false"
    & ".venv\Scripts\python.exe" -m app.preflight
    if ($LASTEXITCODE -ne 0) { throw "Live AWS preflight failed" }
} finally {
    Restore-ProcessEnvironment $environment
    Pop-Location
}
