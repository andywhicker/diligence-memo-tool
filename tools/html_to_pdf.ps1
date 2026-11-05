<#
Convert an SEC EDGAR filing (.htm) into a PDF the tool can read, with one PDF page per
filing page so printed page numbers line up with PDF pages.

Usage:
  .\tools\html_to_pdf.ps1 -Html docs\avav-20260430x10k.htm -Out docs\AVAV_10-K_FY2026_clean.pdf

How it works: copies the HTML to a temp file with a small print stylesheet (tighter margins,
85% zoom so each filing page fits on one Letter page), then asks Microsoft Edge (already on
Windows) to print it to PDF in the background. The original .htm is not modified.

Check the result with:  python diligence.py <pdf> --dry-run
It should report "citation mode: printed" and no pages falling back to "PDF n".
#>
param(
    [Parameter(Mandatory = $true)][string]$Html,
    [Parameter(Mandatory = $true)][string]$Out,
    [double]$Zoom = 0.85
)
$ErrorActionPreference = 'Stop'

$edge = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          "C:\Program Files\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found." }

$src = (Resolve-Path $Html).Path
$outFull = if ([IO.Path]::IsPathRooted($Out)) { $Out } else { [IO.Path]::GetFullPath((Join-Path (Get-Location) $Out)) }
$tmpDir = Join-Path $env:TEMP "diligence-html2pdf"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$tmpHtml = Join-Path $tmpDir "print.htm"

$content = [IO.File]::ReadAllText($src)
$style = "<style>@page { size: letter; margin: 0.25in; } html { zoom: $Zoom; }</style>"
$content = $content -replace '(?i)</head>', "$style</head>"
[IO.File]::WriteAllText($tmpHtml, $content, (New-Object Text.UTF8Encoding $false))

$url = "file:///" + ($tmpHtml -replace '\\', '/')
if (Test-Path $outFull) { Remove-Item $outFull }
# Edge writes harmless log lines to stderr; don't let PowerShell treat them as fatal.
$ErrorActionPreference = 'Continue'
& $edge --headless --disable-gpu --no-pdf-header-footer --user-data-dir="$tmpDir\profile" `
        --print-to-pdf="$outFull" $url 2>$null | Out-Null
$ErrorActionPreference = 'Stop'
Start-Sleep -Seconds 2
if (-not (Test-Path $outFull)) { throw "PDF was not created." }
Write-Host "Wrote $outFull"
