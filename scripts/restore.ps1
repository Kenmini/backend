param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [switch]$ConfirmRestore
)
$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) { throw "Pass -ConfirmRestore to overwrite the active database." }
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    & ".venv\Scripts\python.exe" -m app.database_cli restore $Backup --overwrite
} finally {
    Pop-Location
}
