# Keep AI Business Assistant agents working on Vercel serverless.
# Hits the global autonomy tick so queued agent tasks keep draining.
#
# Usage:
#   $env:CRON_SECRET = "your-secret"   # same as Vercel Production CRON_SECRET
#   .\scripts\keep_autonomy_alive.ps1
#   .\scripts\keep_autonomy_alive.ps1 -Once
#   .\scripts\keep_autonomy_alive.ps1 -IntervalSec 300 -BaseUrl "https://www.aibusinessagent.xyz"
#
# Prefer production Vercel Cron (vercel.json → */5 * * * *) when the plan allows it.
# This script is a backup pinger for Hobby plans (daily-only cron) or offline recovery.

param(
    [string]$BaseUrl = "https://www.aibusinessagent.xyz",
    [int]$IntervalSec = 300,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$secret = $env:CRON_SECRET
if (-not $secret) {
    Write-Error "Set CRON_SECRET env var (Vercel Production → Environment Variables)."
}

$url = ($BaseUrl.TrimEnd("/")) + "/api/ops/autonomy/tick-all"
$headers = @{
    "Authorization" = "Bearer $secret"
    "X-Cron-Secret" = $secret
    "Accept"        = "application/json"
}

function Invoke-Tick {
    $ts = Get-Date -Format "o"
    try {
        $resp = Invoke-RestMethod -Method GET -Uri $url -Headers $headers -TimeoutSec 280
        $users = $resp.result.users
        Write-Host "[$ts] ok via=$($resp.via) users=$users"
        return $true
    } catch {
        Write-Host "[$ts] FAIL $($_.Exception.Message)"
        return $false
    }
}

Write-Host "Autonomy keep-alive → $url every ${IntervalSec}s (Ctrl+C to stop)"
if ($Once) {
    exit $(if (Invoke-Tick) { 0 } else { 1 })
}

while ($true) {
    [void](Invoke-Tick)
    Start-Sleep -Seconds $IntervalSec
}
