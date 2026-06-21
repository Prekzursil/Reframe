# wsl-verthor-bootstrap.ps1 — detect WSL + the verthor env; offer a scripted
# install (PLAN-P2 T5: "detect WSL + verthor; offer a scripted bootstrap ...
# OR rely on the T4b fallback with a clear notice"). BEST-EFFORT, loudly logged.
#
# Detection (default, no flags): reports WSL presence + whether the verthor
# venv exists; exit 0 when ready, exit 2 when the claude-shorts fallback will
# be used (informational), exit 1 only on a hard error during -Install.
#
# Install (-Install): runs build/wsl-verthor-bootstrap.sh INSIDE WSL — the
# script is passed FROM A FILE (`wsl bash <script> <args>`), never piped via
# stdin (CONTRACTS.md §4: mediapipe eats stdin and corrupts piped scripts).
#
# CONTRACT-NOTE: verthor's repo URL is not public knowledge pinned in this
# tree; pass -RepoUrl or set VERTHOR_REPO_URL. Weights likewise (-WeightsUrl).

[CmdletBinding()]
param(
    [switch]$Install,
    [string]$RepoUrl = $env:VERTHOR_REPO_URL,
    [string]$InstallDir = '~/verthor',
    [string]$WeightsUrl = $env:VERTHOR_WEIGHTS_URL
)

$ErrorActionPreference = 'Stop'

function Test-WslCommand {
    # argv-style invocation; returns $true when the command exits 0.
    param([string[]]$CommandArgs)
    & wsl @CommandArgs 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# -- 1. WSL present? -----------------------------------------------------------
$wslExe = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wslExe) {
    Write-Host '[verthor] WSL is not installed.'
    Write-Host '[verthor] NOTICE: reframe will use the claude-shorts engine (T4b fallback).'
    Write-Host '[verthor] To enable verthor: `wsl --install`, reboot, then re-run this script.'
    Write-Host 'SUCCESS:wsl-verthor-bootstrap no-wsl (fallback engine active)'
    exit 2
}
Write-Host "[verthor] wsl.exe found: $($wslExe.Source)"

# A default distro must actually run (wsl.exe can exist with no distro).
if (-not (Test-WslCommand @('-e', 'true'))) {
    Write-Host '[verthor] WSL is installed but no runnable default distro was found.'
    Write-Host '[verthor] NOTICE: reframe will use the claude-shorts engine (T4b fallback).'
    Write-Host '[verthor] Install one with: wsl --install -d Ubuntu'
    Write-Host 'SUCCESS:wsl-verthor-bootstrap no-distro (fallback engine active)'
    exit 2
}

# -- 2. verthor venv present? ----------------------------------------------------
$venvReady = Test-WslCommand @('-e', 'test', '-x', "$InstallDir/.venv/bin/python")
if ($venvReady) {
    Write-Host "[verthor] verthor venv detected at $InstallDir/.venv — nothing to do."
    Write-Host 'SUCCESS:wsl-verthor-bootstrap verthor ready'
    exit 0
}
Write-Host "[verthor] no verthor venv at $InstallDir/.venv"

if (-not $Install) {
    Write-Host '[verthor] NOTICE: reframe will use the claude-shorts engine (T4b fallback).'
    Write-Host '[verthor] Run again with -Install -RepoUrl <url> for the scripted setup.'
    Write-Host 'SUCCESS:wsl-verthor-bootstrap verthor absent (fallback engine active)'
    exit 2
}

# -- 3. scripted install (best-effort) --------------------------------------------
try {
    if (-not $RepoUrl) {
        throw 'no repo URL: pass -RepoUrl or set VERTHOR_REPO_URL'
    }
    $shScript = Join-Path $PSScriptRoot 'wsl-verthor-bootstrap.sh'
    if (-not (Test-Path $shScript)) { throw "missing $shScript" }

    # Translate the Windows script path for WSL — the script runs FROM A FILE.
    $wslScript = (& wsl wslpath -a "$shScript" 2>$null | Select-Object -First 1)
    if (-not $wslScript) { throw "wslpath could not translate $shScript" }

    Write-Host "[verthor] running: wsl bash $wslScript $RepoUrl $InstallDir $(if ($WeightsUrl) { '<weights-url>' })"
    if ($WeightsUrl) {
        & wsl bash "$wslScript" "$RepoUrl" "$InstallDir" "$WeightsUrl"
    } else {
        & wsl bash "$wslScript" "$RepoUrl" "$InstallDir"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "install script exited $LASTEXITCODE (see lines above); the claude-shorts fallback remains active"
    }
    Write-Host 'SUCCESS:wsl-verthor-bootstrap verthor installed'
    exit 0
} catch {
    Write-Host "FAILED:wsl-verthor-bootstrap $($_.Exception.Message)"
    exit 1
}
