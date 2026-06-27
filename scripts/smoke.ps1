param([int]$Port = 8765)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$database = Join-Path $root ("data\smoke-{0}.db" -f [guid]::NewGuid())
$baseUrl = "http://127.0.0.1:$Port"
$process = $null

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

try {
    $env:APP_MODE = "demo"
    $env:ANSWER_PATH = "advanced"
    $env:STORAGE_MODE = "sqlite"
    $env:DATABASE_PATH = $database
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

    $known = @{ message = "輝度つまみはどこですか？"; session_id = "smoke-session" } |
        ConvertTo-Json | Invoke-RestMethod "$baseUrl/ask" -Method Post -ContentType "application/json"
    Assert-True (-not $known.is_gap) "Known fixture unexpectedly returned a gap"

    $unknown = @{ message = "未登録の手順"; session_id = "smoke-session" } |
        ConvertTo-Json | Invoke-RestMethod "$baseUrl/ask" -Method Post -ContentType "application/json"
    Assert-True $unknown.is_gap "Unknown fixture did not return a gap"
    $gaps = Invoke-RestMethod "$baseUrl/gaps"
    Assert-True ($gaps.gaps.Count -gt 0) "Gap was not persisted"

    $onboarding = @{ role = "M1"; field = "光学" } |
        ConvertTo-Json | Invoke-RestMethod "$baseUrl/onboarding" -Method Post -ContentType "application/json"
    Assert-True ([bool]$onboarding.guide) "Onboarding guide is empty"
    $feedback = @{ session_id = "smoke-session"; message = "answer"; rating = "up" } |
        ConvertTo-Json | Invoke-RestMethod "$baseUrl/feedback" -Method Post -ContentType "application/json"
    Assert-True $feedback.ok "Feedback was not recorded"
    Write-Host "All endpoint smoke tests passed."
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    foreach ($path in @($database, "$database-wal", "$database-shm")) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}
