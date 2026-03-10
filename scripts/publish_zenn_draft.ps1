# publish_zenn_draft.ps1
# docs/drafts/stock_system_zenn_draft.md を articles/ に同期して GitHub へ push する
# 使い方: powershell -ExecutionPolicy Bypass -File scripts/publish_zenn_draft.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root "docs\drafts\stock_system_zenn_draft.md"
$dest = Join-Path $root "articles\stock-screening-automation.md"

# 1. 最新ドラフトを articles/ へ上書きコピー
Copy-Item -Path $src -Destination $dest -Force
Write-Host "Copied: $dest"

# 2. git add + commit + push
Push-Location $root
try {
    git add "articles/stock-screening-automation.md"
    $status = git status --porcelain
    if (-not $status) {
        Write-Host "No changes to commit. Zenn draft is already up to date."
        exit 0
    }
    $date = Get-Date -Format "yyyy-MM-dd"
    git commit -m "docs: update Zenn draft ($date)"
    git push
    Write-Host "Pushed to GitHub. Zenn will sync automatically."
} finally {
    Pop-Location
}
