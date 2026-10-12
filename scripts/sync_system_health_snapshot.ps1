# Sync the S13 multi-host health snapshot into a local read-only mirror.
#
# Why this exists
# ---------------
# The Streamlit UI must never SSH and never probe hardware.  It reads a file
# snapshot (see src/services/system_health_read.py).  On S13 that file lives at
# /var/lib/crm-system-health/latest.json, which obviously does not exist on a
# Windows workstation -- that is why the «Состояние серверов» page showed
# "Collector down".  This script mirrors the snapshot through the already
# approved SSH route; the UI then reads the mirror via CRM_SYSTEM_HEALTH_DIR.
#
# Usage
#   powershell -File scripts/sync_system_health_snapshot.ps1            # one shot
#   powershell -File scripts/sync_system_health_snapshot.ps1 -Loop 15   # keep fresh
param(
    [string]$HostAlias = "mint-lan",
    [string]$RemoteDir = "/var/lib/crm-system-health",
    [string]$LocalDir  = "C:\Users\Lenovo\AppData\Local\crm-system-health",
    [int]$Loop = 0
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

function Sync-Once {
    $tmp = Join-Path $LocalDir "latest.json.tmp"
    scp -q "${HostAlias}:$RemoteDir/latest.json" $tmp
    if (Test-Path $tmp) {
        Move-Item -LiteralPath $tmp -Destination (Join-Path $LocalDir "latest.json") -Force
    }
    $hist = Join-Path $LocalDir "history.sqlite3"
    scp -q "${HostAlias}:$RemoteDir/history.sqlite3" $hist
}

if ($Loop -gt 0) {
    while ($true) {
        try { Sync-Once } catch { Write-Warning "sync failed: $_" }
        Start-Sleep -Seconds $Loop
    }
} else {
    Sync-Once
    Write-Output "synced -> $LocalDir\latest.json"
}