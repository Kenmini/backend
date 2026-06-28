param([int]$Port = 8766)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-env.ps1")
$python = Join-Path $root ".venv\Scripts\python.exe"
$database = Join-Path $root ("data\live-smoke-{0}.db" -f [guid]::NewGuid())
$baseUrl = "http://127.0.0.1:$Port"
$process = $null
$environment = Save-ProcessEnvironment @(
    "APP_MODE", "ANSWER_PATH", "STORAGE_MODE", "DATABASE_PATH",
    "GAP_THRESHOLD", "PUBLIC_DEMO"
)

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

try {
    $env:APP_MODE = "live"
    $env:ANSWER_PATH = "advanced"
    $env:STORAGE_MODE = "sqlite"
    $env:DATABASE_PATH = $database
    # Weak/empty retrieval cutoff; Sonnet performs the final support audit.
    $env:GAP_THRESHOLD = "0.20"
    $env:PUBLIC_DEMO = "false"
    $process = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $Port,
        "--app-dir", $root
    ) -PassThru -WindowStyle Hidden

    $ready = $false
    for ($attempt = 0; $attempt -lt 160; $attempt++) {
        try {
            $health = Invoke-RestMethod "$baseUrl/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True $ready "Server did not become healthy"

    $readiness = Invoke-RestMethod "$baseUrl/ready" -TimeoutSec 10
    Assert-True ($readiness.status -eq "ready") "Readiness check failed"

    $knownBody = ConvertTo-Utf8JsonBytes @{
        message = "HF-2000の液体窒素は最初の補充後どのくらいの間隔で補充しますか？"
        session_id = "live-smoke"
    }
    $known = Invoke-RestMethod "$baseUrl/ask" -Method Post -ContentType "application/json" -Body $knownBody -TimeoutSec 90
    Assert-True (-not $known.is_gap) "Known live query unexpectedly returned a gap"
    Assert-True ($known.citations.Count -gt 0) "Known live query returned no citations"
    Assert-True ($known.visual_data.image_url.StartsWith("data:image/jpeg;base64,")) "Known live query returned no PDF page image"
    Assert-True ($known.visual_data.source -eq "hf2000_manual_tem_edx_nbd_dstem.pdf") "Known live query returned the wrong visual source"
    Assert-True ($known.visual_data.page_number -gt 0) "Known live query returned no visual page number"

    $gapBody = ConvertTo-Utf8JsonBytes @{
        message = "研究室のWi-Fiパスワードは何ですか？"
        session_id = "live-smoke"
    }
    $gap = Invoke-RestMethod "$baseUrl/ask" -Method Post -ContentType "application/json" -Body $gapBody -TimeoutSec 90
    Assert-True $gap.is_gap "Calibrated live gap query did not return a gap"
    Assert-True ($gap.citations.Count -eq 0) "Gap response returned citations"

    $onboardingBody = ConvertTo-Utf8JsonBytes @{ role = "M1"; field = "光学" }
    $onboarding = Invoke-RestMethod "$baseUrl/onboarding" -Method Post -ContentType "application/json" -Body $onboardingBody -TimeoutSec 90
    Assert-True ([bool]$onboarding.guide) "Live onboarding guide is empty"
    Write-Host "Live Sonnet, Haiku, retrieval, gap, and endpoint smoke tests passed."
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    foreach ($path in @($database, "$database-wal", "$database-shm")) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
    Restore-ProcessEnvironment $environment
}
