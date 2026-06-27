$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    & ".venv\Scripts\python.exe" -m app.database_cli backup
} finally {
    Pop-Location
}
