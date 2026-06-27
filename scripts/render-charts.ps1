$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $root "docs\architecture"
$output = Join-Path $root "images/charts"
$package = "@mermaid-js/mermaid-cli@11.12.0"

New-Item -ItemType Directory -Force -Path $output | Out-Null
Get-ChildItem -LiteralPath $source -Filter "*.mmd" | ForEach-Object {
    $name = $_.BaseName
    & npx --yes $package -i $_.FullName -o (Join-Path $output "$name.svg") -b transparent
    if ($LASTEXITCODE -ne 0) { throw "SVG rendering failed for $name" }
    & npx --yes $package -i $_.FullName -o (Join-Path $output "$name.png") -b white -w 1600
    if ($LASTEXITCODE -ne 0) { throw "PNG rendering failed for $name" }
}

Write-Host "Rendered charts to $output"
