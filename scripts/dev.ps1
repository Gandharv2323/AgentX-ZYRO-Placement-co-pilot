# Dev launcher: starts the API and the web app, waits for both, prints the URL.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$apiPort = if ($env:PLACEPILOT_API_PORT) { $env:PLACEPILOT_API_PORT } else { 8010 }
$webPort = if ($env:PLACEPILOT_WEB_PORT) { $env:PLACEPILOT_WEB_PORT } else { 3210 }

$env:TMP = Join-Path $root '.cache\tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

# caches must live in the repo: AppData is not writable in some environments
$env:UV_CACHE_DIR = Join-Path $root '.cache\uv'
$env:npm_config_cache = Join-Path $root '.cache\npm'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:PLACEPILOT_DB = Join-Path $root 'apps\api\data\placepilot.db'

Write-Host "· API  -> http://127.0.0.1:$apiPort"
Write-Host "· Web  -> http://127.0.0.1:$webPort"

Start-Process -FilePath (Join-Path $root 'apps\api\.venv\Scripts\python.exe') `
  -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$apiPort" `
  -WorkingDirectory (Join-Path $root 'apps\api')
Start-Process -FilePath 'npx' -ArgumentList 'next', 'start', '-p', "$webPort" `
  -WorkingDirectory (Join-Path $root 'apps\web')

foreach ($i in 1..40) {
  try {
    $null = Invoke-WebRequest "http://127.0.0.1:$apiPort/healthz" -UseBasicParsing -TimeoutSec 2
    break
  } catch { Start-Sleep -Milliseconds 500 }
}

Write-Host "`nOpen http://127.0.0.1:$webPort"
