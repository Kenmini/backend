param([int]$Port = 8765)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$python = Join-Path $root ".venv\Scripts\python.exe"
$database = Join-Path $root ("data\smoke-{0}.db" -f [guid]::NewGuid())
$baseUrl = "http://127.0.0.1:$Port"
$process = $null
$environment = Save-ProcessEnvironment @(
    "APP_MODE", "ANSWER_PATH", "STORAGE_MODE", "DATABASE_PATH", "PUBLIC_DEMO"
)

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

try {
    $env:APP_MODE = "demo"
    $env:ANSWER_PATH = "advanced"
    $env:STORAGE_MODE = "sqlite"
    $env:DATABASE_PATH = $database
    $env:PUBLIC_DEMO = "false"
    $process = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $Port,
        "--app-dir", $root
    ) -PassThru -WindowStyle Hidden

    $ready = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        try {
            $health = Invoke-RestMethod "$baseUrl/health"
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True $ready "Server did not become healthy"

    $readiness = Invoke-RestMethod "$baseUrl/ready"
    Assert-True ($readiness.status -eq "ready") "Readiness check failed"
    $faq = Invoke-RestMethod "$baseUrl/faq"
    Assert-True ($faq.items.Count -gt 0) "FAQ is empty"

    $known = Invoke-RestMethod "$baseUrl/ask" -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body (ConvertTo-Utf8JsonBytes @{
            message = "輝度つまみはどこですか？"
            session_id = "smoke-session"
        })
    Assert-True (-not $known.is_gap) "Known fixture unexpectedly returned a gap"

    $unknown = Invoke-RestMethod "$baseUrl/ask" -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body (ConvertTo-Utf8JsonBytes @{
            message = "未登録の手順"
            session_id = "smoke-session"
        })
    Assert-True $unknown.is_gap "Unknown fixture did not return a gap"
    $gaps = Invoke-RestMethod "$baseUrl/gaps"
    Assert-True ($gaps.gaps.Count -gt 0) "Gap was not persisted"

    $onboarding = Invoke-RestMethod "$baseUrl/onboarding" -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body (ConvertTo-Utf8JsonBytes @{ role = "M1"; field = "光学" })
    Assert-True ([bool]$onboarding.guide) "Onboarding guide is empty"
    $feedback = Invoke-RestMethod "$baseUrl/feedback" -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body (ConvertTo-Utf8JsonBytes @{
            session_id = "smoke-session"
            message = "answer"
            rating = "up"
        })
    Assert-True $feedback.ok "Feedback was not recorded"
    Write-Host "All endpoint smoke tests passed."
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    foreach ($path in @($database, "$database-wal", "$database-shm")) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
    Restore-ProcessEnvironment $environment
}
