$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    & ".venv\Scripts\python.exe" -m app.database_cli backup
    if ($LASTEXITCODE -ne 0) { throw "Database backup failed" }
} finally {
    Pop-Location
}
