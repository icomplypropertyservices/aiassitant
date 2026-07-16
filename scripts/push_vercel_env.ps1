# Push .env.production.local into Vercel Production (and optional Preview).
# Requires: vercel login  OR  $env:VERCEL_TOKEN
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts/push_vercel_env.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/push_vercel_env.ps1 -Preview

param(
  [switch]$Preview,
  [string]$EnvFile = ".env.production.local"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$envPath = Join-Path $root $EnvFile
if (-not (Test-Path $envPath)) {
  throw "Missing $EnvFile - run scripts/_merge_prod_env.py first"
}

if (-not (Test-Path ".vercel/project.json")) {
  throw "Project not linked (.vercel/project.json missing). Run: vercel link"
}

$who = & vercel whoami 2>&1
if ($LASTEXITCODE -ne 0) {
  throw "Vercel CLI not authenticated. Run: vercel login   OR set VERCEL_TOKEN"
}
Write-Host "Logged in as: $who"

$targets = @("production")
if ($Preview) { $targets += "preview" }

$lines = Get-Content $envPath | Where-Object {
  $_ -and ($_ -notmatch '^\s*#') -and ($_ -match '=')
}

$ok = 0
$fail = 0
foreach ($line in $lines) {
  $idx = $line.IndexOf('=')
  if ($idx -lt 1) { continue }
  $key = $line.Substring(0, $idx).Trim()
  $val = $line.Substring($idx + 1)
  if ([string]::IsNullOrWhiteSpace($key)) { continue }
  if ($key -match '^(VITE_|OLLAMA_)') {
    Write-Host "skip $key (frontend/local only)"
    continue
  }

  foreach ($t in $targets) {
    Write-Host "Setting $key -> $t ..."
    & vercel env rm $key $t -y 2>$null | Out-Null
    $val | & vercel env add $key $t 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
      $ok++
      Write-Host "  OK $key ($t)"
    } else {
      $fail++
      Write-Host "  FAIL $key ($t)"
    }
  }
}

Write-Host ""
Write-Host "Done. ok=$ok fail=$fail"
Write-Host "Redeploy production with: vercel --prod"
