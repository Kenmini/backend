param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("demo", "live")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$Token,

    [Parameter(Mandatory = $true)]
    [string]$FrontendOrigin
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$BaseUrl = $BaseUrl.TrimEnd("/")

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-CheckedRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Method = "GET",
        [hashtable]$Headers = @{},
        [object]$Body,
        [int]$ExpectedStatus = 200
    )

    $arguments = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        Headers = $Headers
        UseBasicParsing = $true
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 10
        $arguments.ContentType = "application/json; charset=utf-8"
        $arguments.Body = [Text.Encoding]::UTF8.GetBytes($json)
    }

    try {
        $response = Invoke-WebRequest @arguments
        $status = [int]$response.StatusCode
    } catch {
        if ($null -eq $_.Exception.Response) { throw }
        $response = $_.Exception.Response
        $status = [int]$response.StatusCode
    }

    Assert-True ($status -eq $ExpectedStatus) "$Method $Path returned $status; expected $ExpectedStatus"
    return $response
}

Assert-True ($BaseUrl -match '^https://') "Public smoke tests require an HTTPS URL"
$authorized = @{ "X-Demo-Token" = $Token }

$health = Invoke-CheckedRequest -Path "/health"
Assert-True ([bool]$health.Headers["X-Request-ID"]) "Health response has no request ID"
Invoke-CheckedRequest -Path "/ready" -ExpectedStatus 401 | Out-Null
$readyResponse = Invoke-CheckedRequest -Path "/ready" -Headers $authorized
$ready = $readyResponse.Content | ConvertFrom-Json
Assert-True ($ready.mode -eq $Mode) "Readiness mode is '$($ready.mode)', expected '$Mode'"

foreach ($path in @("/docs", "/redoc", "/openapi.json")) {
    Invoke-CheckedRequest -Path $path -Headers $authorized -ExpectedStatus 404 | Out-Null
}

$preflightHeaders = @{
    Origin = $FrontendOrigin
    "Access-Control-Request-Method" = "POST"
    "Access-Control-Request-Headers" = "content-type,x-demo-token"
}
$preflight = Invoke-CheckedRequest -Path "/ask" -Method "OPTIONS" -Headers $preflightHeaders
Assert-True ($preflight.Headers["Access-Control-Allow-Origin"] -contains $FrontendOrigin) "Configured frontend origin was not allowed"

$untrustedOrigin = "https://untrusted.invalid"
$rejected = Invoke-CheckedRequest -Path "/ask" -Method "OPTIONS" -Headers @{
    Origin = $untrustedOrigin
    "Access-Control-Request-Method" = "POST"
    "Access-Control-Request-Headers" = "content-type,x-demo-token"
} -ExpectedStatus 400
Assert-True ($rejected.Headers["Access-Control-Allow-Origin"] -notcontains $untrustedOrigin) "Untrusted origin was allowed"

$faqResponse = Invoke-CheckedRequest -Path "/faq" -Headers $authorized
$faq = $faqResponse.Content | ConvertFrom-Json
Assert-True ($faq.items.Count -gt 0) "FAQ is empty"
Assert-True ($faqResponse.Content -match "研究室") "Japanese FAQ text was not decoded as UTF-8"

$question = if ($Mode -eq "demo") { "輝度つまみはどこですか？" } else { "研究室の安全ルール" }
$askResponse = Invoke-CheckedRequest -Path "/ask" -Method "POST" -Headers $authorized -Body @{
    message = $question
    session_id = "public-smoke"
}
$answer = $askResponse.Content | ConvertFrom-Json
Assert-True ([bool]$answer.answer_text) "Ask response is empty"
if ($Mode -eq "demo") {
    Assert-True (-not $answer.is_gap) "Known demo fixture unexpectedly returned a gap"
}

$onboardingResponse = Invoke-CheckedRequest -Path "/onboarding" -Method "POST" -Headers $authorized -Body @{
    role = "M1"
    field = "光学"
}
$onboarding = $onboardingResponse.Content | ConvertFrom-Json
Assert-True ([bool]$onboarding.guide) "Onboarding response is empty"

Write-Host "Public HTTPS smoke tests passed for $BaseUrl ($Mode mode)."
