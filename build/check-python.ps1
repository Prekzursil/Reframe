# check-python.ps1 — CI-style dev-python pin assert (PLAN-P2 T5).
#
# The whole stack is pinned to CPython 3.12 (CONTRACTS.md §7; the embeddable
# runtime, the wheels in requirements-sidecar.txt, mediapipe's wheel matrix).
# A stray 3.14 __pycache__ was found in the tree once — this script makes the
# pin enforceable: it FAILS (exit 1) unless the dev environment is 3.12.
#
# Checks:
#   1. `py -3.12` resolves and reports 3.12.x
#   2. sidecar/.venv (if present) was built from 3.12.x
#   3. no stray 3.13/3.14 bytecode in the repo source tree (outside .venv)
#
# Offline + read-only. Output is terminal-state: SUCCESS:/FAILED: lines.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$failures = @()

# -- 1. py launcher must offer 3.12 -----------------------------------------
$pyVersion = $null
try {
    $pyVersion = (& py -3.12 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null) | Select-Object -First 1
} catch {
    $pyVersion = $null
}
if (-not $pyVersion -or -not $pyVersion.StartsWith('3.12.')) {
    $failures += "py -3.12 launcher missing or wrong (got: '$pyVersion'); install CPython 3.12 x64"
} else {
    Write-Host "[check-python] py -3.12 -> $pyVersion"
}

# -- 2. sidecar/.venv must be 3.12 -------------------------------------------
$venvCfg = Join-Path $RepoRoot 'sidecar\.venv\pyvenv.cfg'
if (Test-Path $venvCfg) {
    $versionLine = (Get-Content $venvCfg | Where-Object { $_ -match '^\s*version\s*=' }) | Select-Object -First 1
    $venvVersion = if ($versionLine) { ($versionLine -split '=', 2)[1].Trim() } else { '' }
    if (-not $venvVersion.StartsWith('3.12.')) {
        $failures += "sidecar/.venv is python '$venvVersion' (rebuild it with py -3.12 -m venv)"
    } else {
        Write-Host "[check-python] sidecar/.venv -> $venvVersion"
    }
} else {
    Write-Host "[check-python] sidecar/.venv not present (skipped)"
}

# -- 3. no stray 3.13/3.14 bytecode in the source tree -----------------------
$strays = Get-ChildItem -Path $RepoRoot -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match 'cpython-31[3-9]' -and
        $_.FullName -notmatch '\\\.venv\\' -and
        $_.FullName -notmatch '\\node_modules\\'
    }
if ($strays) {
    $list = ($strays | Select-Object -First 10 | ForEach-Object { $_.FullName }) -join '; '
    $failures += "stray non-3.12 bytecode found (purge these __pycache__ dirs): $list"
}

# -- verdict ------------------------------------------------------------------
if ($failures.Count -gt 0) {
    foreach ($f in $failures) { Write-Host "FAILED:check-python $f" }
    exit 1
}
Write-Host 'SUCCESS:check-python dev environment is pinned to CPython 3.12'
exit 0
