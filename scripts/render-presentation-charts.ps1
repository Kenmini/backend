$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $root "docs\presentation"
$output = Join-Path $root "images\charts"
$package = "@mermaid-js/mermaid-cli@11.12.0"

New-Item -ItemType Directory -Force -Path $output | Out-Null

foreach ($language in @("en", "ja")) {
    foreach ($theme in @("light", "dark")) {
        $config = Join-Path $source "themes\$theme.json"
        $background = if ($theme -eq "dark") { "#020617" } else { "#f8fafc" }
        Get-ChildItem -LiteralPath (Join-Path $source $language) -Filter "*.mmd" |
            Sort-Object Name | ForEach-Object {
                $stem = "presentation-$language-$theme-$($_.BaseName)"
                foreach ($extension in @(".svg", ".png")) {
                    $target = Join-Path $output "$stem$extension"
                    & npx --yes $package -i $_.FullName -o $target -c $config `
                        -b $background -w 1920 -H 1080 -s 2 -q
                    if ($LASTEXITCODE -ne 0) { throw "Rendering failed: $target" }
                    if (-not (Test-Path $target) -or (Get-Item $target).Length -eq 0) {
                        throw "Renderer produced an empty file: $target"
                    }
                }
            }
    }
}

Write-Host "Rendered bilingual presentation charts to $output"
