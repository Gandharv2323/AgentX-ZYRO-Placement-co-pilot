# Full verification: unit/flow tests, typecheck+build, browser golden path, layout QA.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:TMP = Join-Path $root '.cache\tmp'; $env:TEMP = $env:TMP
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:PYTEST_ADDOPTS = '-p no:cacheprovider'

Write-Host "`n== pytest ==" -ForegroundColor Cyan
Push-Location (Join-Path $root 'apps\api'); & .\.venv\Scripts\python.exe -m pytest; Pop-Location

Write-Host "`n== build ==" -ForegroundColor Cyan
Push-Location (Join-Path $root 'apps\web'); npm run build; Pop-Location

Write-Host "`n== e2e + qa ==" -ForegroundColor Cyan
Write-Host "Requires both servers running (scripts\dev.ps1)."
node (Join-Path $root 'scripts\e2e.mjs')
node (Join-Path $root 'scripts\qa.mjs')
