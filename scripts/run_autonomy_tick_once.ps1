$ErrorActionPreference = "Continue"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -ErrorAction SilentlyContinue
if (-not $root) { $root = "C:\Users\E-Store\ai-business-assistant\ai-business-assistant" }
# script lives in scripts/, so parent is project root
$root = Split-Path $PSScriptRoot -Parent
$secPath = Join-Path $root ".cron_secret_tmp"
$log = Join-Path $PSScriptRoot "autonomy_keepalive.log"
if (-not (Test-Path $secPath)) { Add-Content $log "$(Get-Date -Format o) FAIL missing cron secret file"; exit 1 }
$env:CRON_SECRET = (Get-Content $secPath -Raw).Trim()
& (Join-Path $PSScriptRoot "keep_autonomy_alive.ps1") -Once -IntervalSec 300 -BaseUrl "https://www.aibusinessagent.xyz" *>> $log 2>&1
