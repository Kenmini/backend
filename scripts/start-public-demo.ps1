param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("demo", "live")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string[]]$FrontendOrigin,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = $null
$tunnel = $null
$tunnelOut = Join-Path $env:TEMP ("umpjust-cloudflared-{0}.out.log" -f [guid]::NewGuid())
$tunnelError = Join-Path $env:TEMP ("umpjust-cloudflared-{0}.error.log" -f [guid]::NewGuid())

function Assert-ValidOrigin([string]$Origin) {
    $uri = $null
    $valid = [Uri]::TryCreate($Origin, [UriKind]::Absolute, [ref]$uri)
    if (-not $valid -or $uri.Scheme -notin @("http", "https") -or $Origin.Contains("*")) {
        throw "Invalid frontend origin: $Origin"
    }
}

function New-DemoToken {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Create .venv and install the project dependencies first."
}
if ($FrontendOrigin.Count -eq 0) { throw "At least one frontend origin is required." }
$FrontendOrigin | ForEach-Object { Assert-ValidOrigin $_ }

$cloudflaredCommand = Get-Command "cloudflared" -ErrorAction SilentlyContinue
if (-not $cloudflaredCommand) {
    throw "cloudflared is not installed. Run: winget install --id Cloudflare.cloudflared --exact"
}

try {
    Push-Location $root
    if ($Mode -eq "live") {
        & (Join-Path $PSScriptRoot "preflight.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Live AWS preflight failed; the public server was not started." }
    }

    $token = New-DemoToken
    $env:APP_MODE = $Mode
    $env:ANSWER_PATH = "advanced"
    $env:PUBLIC_DEMO = "true"
    $env:DEMO_API_TOKEN = $token
    $env:CORS_ORIGINS = $FrontendOrigin -join ","
    $env:STORAGE_MODE = "sqlite"
    $env:DATABASE_PATH = "data/public-$Mode.db"

    $backend = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $Port,
        "--app-dir", $root
    ) -PassThru -WindowStyle Hidden

    $localUrl = "http://127.0.0.1:$Port"
    $healthy = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($backend.HasExited) { throw "The backend exited before it became healthy." }
        try {
            $health = Invoke-RestMethod "$localUrl/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $healthy) { throw "The backend did not become healthy at $localUrl." }

    $commandDisplay = "cloudflared tunnel --url $localUrl"
    Write-Host "Starting: $commandDisplay"
    $publicUrl = $null
    $publicReady = $false
    for ($tunnelAttempt = 1; $tunnelAttempt -le 3 -and -not $publicReady; $tunnelAttempt++) {
        Remove-Item -LiteralPath $tunnelOut, $tunnelError -Force -ErrorAction SilentlyContinue
        $tunnel = Start-Process -FilePath $cloudflaredCommand.Source -ArgumentList @(
            "tunnel", "--url", $localUrl, "--no-autoupdate"
        ) -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelError -PassThru -WindowStyle Hidden

        $publicUrl = $null
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            if ($tunnel.HasExited) { break }
            $logs = (Get-Content $tunnelOut -Raw -ErrorAction SilentlyContinue) + "`n" +
                (Get-Content $tunnelError -Raw -ErrorAction SilentlyContinue)
            $match = [regex]::Match($logs, 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($match.Success) { $publicUrl = $match.Value; break }
            Start-Sleep -Milliseconds 250
        }

        if ($publicUrl -and -not $tunnel.HasExited) {
            Write-Host "Checking temporary URL (attempt $tunnelAttempt of 3): $publicUrl"
            $publicHost = ([uri]$publicUrl).Host
            $dnsReady = $false
            for ($attempt = 0; $attempt -lt 40; $attempt++) {
                if ($tunnel.HasExited) { break }
                try {
                    Resolve-DnsName $publicHost -Server "1.1.1.1" -DnsOnly -ErrorAction Stop | Out-Null
                    $dnsReady = $true
                    break
                } catch { Start-Sleep -Milliseconds 500 }
            }
            if ($dnsReady) {
                try {
                    $publicHealth = Invoke-WebRequest "$publicUrl/health" -UseBasicParsing -TimeoutSec 10
                    $publicReady = $publicHealth.StatusCode -eq 200
                } catch { $publicReady = $false }
            }
        }

        if (-not $publicReady) {
            Write-Warning "Quick Tunnel attempt $tunnelAttempt was not reachable; requesting a new URL."
            if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
            $tunnel = $null
        }
    }
    if (-not $publicReady) { throw "No public Quick Tunnel became healthy after 3 attempts." }

    Write-Host ""
    Write-Host "Temporary backend: $publicUrl"
    Write-Host "Frontend origins: $($FrontendOrigin -join ', ')"
    Write-Host "X-Demo-Token: $token"
    Write-Host "Do not commit or share the token outside the hackathon team."
    Write-Host ""

    & (Join-Path $PSScriptRoot "smoke-public.ps1") `
        -Mode $Mode -BaseUrl $publicUrl -Token $token -FrontendOrigin $FrontendOrigin[0]

    Write-Host "Tunnel is active. Press Ctrl+C to stop both processes and invalidate the URL."
    while (-not $backend.HasExited -and -not $tunnel.HasExited) {
        Start-Sleep -Seconds 1
    }
    if ($backend.HasExited) { throw "The backend stopped unexpectedly." }
    if ($tunnel.HasExited) { throw "The Cloudflare tunnel stopped unexpectedly." }
} finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    Remove-Item -LiteralPath $tunnelOut, $tunnelError -Force -ErrorAction SilentlyContinue
    Pop-Location -ErrorAction SilentlyContinue
    Remove-Item Env:DEMO_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:PUBLIC_DEMO -ErrorAction SilentlyContinue
}
