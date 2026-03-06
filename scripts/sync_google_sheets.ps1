Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -B (Join-Path $PSScriptRoot "sync_google_sheets.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
