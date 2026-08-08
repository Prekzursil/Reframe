<#
.SYNOPSIS
  Static analysis + self-test for this repo's PowerShell, since no CI gate covers `.ps1`.

.DESCRIPTION
  HONEST SCOPE, STATED UP FRONT: this is NOT wired into CI, so nothing forces it to run.
  QUALITY-CHARTER.md rule 2 declares the six-gate list closed, and `.quality/charter_check.py`
  fails any `gate-<slug>` step in quality.yml without a charter row -- so adding a seventh
  gate is a charter amendment, not a config edit. The gap is therefore real and this file
  does not pretend otherwise: it makes the check one command instead of zero, and names what
  is unenforced.

  Everything here is developer TOOLING (`scripts/**`). No `.ps1` in this repo ships inside
  the Electron app or the Python sidecar, which is why the exposure is bounded -- a defect
  here breaks a maintenance script, not the product.

  Three checks:
    1. PARSE  -- every tracked `.ps1` through PowerShell's own parser. No module needed, so
                 this half always runs. It is the check that would have caught nothing in the
                 recursion incident below, which is exactly why 3 exists.
    2. PSSA   -- PSScriptAnalyzer at Error+Warning, IF the module is installed. Skipped, and
                 said out loud, when it is not: a silent skip would make this script report
                 clean while measuring half of what it claims.
    3. SELFTEST -- scripts/lib/branch-containment-selftest.ps1, the both-states proof for the
                 predicate that authorises `git branch -D`.

.NOTES
  Run:  pwsh -NoProfile -File scripts/lib/ps-lint.ps1
  Install the analyzer once:  Install-Module PSScriptAnalyzer -Scope CurrentUser
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = (& git rev-parse --show-toplevel 2>$null | Select-Object -First 1)
if (-not $repo) { Write-Output 'FAILED:ps-lint not inside a git repo'; exit 1 }
$repo = "$repo".Trim()

$files = @(& git -C $repo ls-files '*.ps1') | Where-Object { $_ }
if ($files.Count -eq 0) {
  # FAIL CLOSED (rules/common/ci-hygiene.md 1): an empty walk means the enumerator broke,
  # not that the repo is clean.
  Write-Output 'FAILED:ps-lint zero .ps1 files enumerated -- the walk is broken'
  exit 1
}
Write-Output "ps-lint: $($files.Count) tracked .ps1 file(s)"

$failures = 0

# ---- 1. parse ---------------------------------------------------------------
foreach ($rel in $files) {
  $full = Join-Path $repo $rel
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$null, [ref]$errors)
  if ($errors -and $errors.Count) {
    Write-Output "  PARSE-FAIL $rel :: $($errors[0].Message)"
    $failures++
  }
}
Write-Output "  parse: $($files.Count - $failures)/$($files.Count) clean"

# ---- 2. PSScriptAnalyzer ----------------------------------------------------
$pssa = Get-Module -ListAvailable PSScriptAnalyzer | Select-Object -First 1
if (-not $pssa) {
  Write-Output '  pssa: SKIPPED (PSScriptAnalyzer not installed) -- this run did NOT lint'
}
else {
  Import-Module PSScriptAnalyzer -ErrorAction Stop
  $found = @(Invoke-ScriptAnalyzer -Path (Join-Path $repo 'scripts') -Recurse -Severity Error, Warning)
  foreach ($d in $found) {
    Write-Output "  $($d.Severity.ToString().ToUpper()) $($d.RuleName) $($d.ScriptName):$($d.Line) $($d.Message)"
  }
  Write-Output "  pssa: v$($pssa.Version) $($found.Count) finding(s)"
  $failures += $found.Count
}

# ---- 3. the containment both-states proof -----------------------------------
$selftest = Join-Path $repo 'scripts/lib/branch-containment-selftest.ps1'
if (Test-Path -LiteralPath $selftest) {
  & pwsh -NoProfile -NonInteractive -File $selftest
  if ($LASTEXITCODE -ne 0) { Write-Output '  selftest: FAILED'; $failures++ }
}
else {
  Write-Output "  selftest: MISSING at $selftest"
  $failures++
}

if ($failures) { Write-Output "FAILED:ps-lint $failures issue(s)"; exit 1 }
Write-Output 'SUCCESS:ps-lint parse + analyzer + containment selftest all clean'
exit 0
