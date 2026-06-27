function Save-ProcessEnvironment([string[]]$Names) {
    $snapshot = @{}
    foreach ($name in $Names) {
        $snapshot[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    return $snapshot
}

function Restore-ProcessEnvironment([hashtable]$Snapshot) {
    foreach ($name in $Snapshot.Keys) {
        $value = $Snapshot[$name]
        if ($null -eq $value) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$name" -Value $value
        }
    }
}

function ConvertTo-Utf8JsonBytes([object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 10
    Write-Output -NoEnumerate ([Text.Encoding]::UTF8.GetBytes($json))
}
