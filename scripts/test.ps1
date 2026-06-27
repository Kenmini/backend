$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    $env:PYTHONIOENCODING = "utf-8"
    & ".venv\Scripts\python.exe" -m pytest --cov=app --cov=config --cov=figures --cov-report=term-missing --cov-fail-under=85
    if ($LASTEXITCODE -ne 0) { throw "Test suite failed" }
} finally {
    Pop-Location
}
