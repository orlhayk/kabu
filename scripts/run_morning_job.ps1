Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
python -B (Join-Path $PSScriptRoot "refresh_watchlist_from_universe.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python -B (Join-Path $PSScriptRoot "build_morning_candidates.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Updated:"
Write-Host "  data/watchlist.csv"
Write-Host "  data/watchlist_live.csv"
Write-Host "  data/sbi_candidates.csv"
Write-Host "  data/sheets_candidates.csv"
Write-Host "  data/sheets_rationale.csv"
Write-Host "  data/sheets_morning_memo.csv"
Write-Host "  reports/dashboard.html"
