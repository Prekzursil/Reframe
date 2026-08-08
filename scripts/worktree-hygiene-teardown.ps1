<#
.SYNOPSIS
  Safely retire agent worktrees (and their branches) whose work has landed on the base ref.

.DESCRIPTION
  The destructive half of scripts/worktree-hygiene-audit.ps1. Removes ONLY worktrees the
  audit classifies as fully landed, one at a time, re-verifying the receipt and the primary
  checkout's health between every single step.

  THE JUNCTION HAZARD, stated as measured rather than as folklore.
  Each worktree carries app/node_modules and app/render-cli/node_modules as JUNCTIONS into
  the primary checkout. Two distinct facts, both verified on this machine 2026-08-08:
    1. `git worktree remove` REFUSES a worktree while those junctions exist -- it walks
       into them, sees hundreds of untracked files, and aborts. This is the reason the
       unlink step is mandatory, and it is not the reason usually given.
    2. Whether a recursive delete follows a junction and destroys the TARGET depends on the
       tool. PowerShell 7's Remove-Item was measured NOT to (link removed, target intact),
       but other tools (shutil.rmtree, some archivers) are UNVERIFIED here -- settle per
       tool by pointing it at a scratch junction and counting the target's files after.
       Because the answer is tool-dependent, this script never recursively deletes a
       worktree directory at all. It unlinks first, always, and lets git do the removal.

  The primary's node_modules is a single point of failure for EVERY concurrent worktree, so
  damage is checked after each teardown, not once at the end, and any drop aborts the loop.

.PARAMETER WhatIf
  Print the plan and the per-item receipts without removing anything.

.PARAMETER Limit
  Process at most N worktrees. Use -Limit 1 for the first run to observe real behaviour
  before committing to a loop.
#>
[CmdletBinding()]
param(
  [string]$Repo = 'C:\Users\Prekzursil\Documents\GitHub\Reframe',
  [string]$Pool = 'C:\Users\Prekzursil\.claude\agent-worktrees',
  [datetime]$CohortStart = '2026-07-31 23:00',
  [datetime]$CohortEnd = '2026-08-01 01:00',
  [string]$Base = 'origin/main',
  [switch]$WhatIf,
  [int]$Limit = 0
)

$ErrorActionPreference = 'Stop'
$prep = Join-Path $PSScriptRoot 'prepare-worktree.ps1'
. (Join-Path $PSScriptRoot 'lib\branch-containment.ps1')

# Pin to an immutable SHA before anything else. Re-resolving the ref per probe raced two
# Dependabot merges mid-run and flipped 14 receipts inside one loop.
$baseSha = Get-BaseSha -Repo $Repo -Ref $Base
$baseTree = Get-TreeOf -Repo $Repo -Rev $baseSha

# Baseline the resource every other worktree on this machine depends on.
$nmApp = Join-Path $Repo 'app\node_modules'
$nmCli = Join-Path $Repo 'app\render-cli\node_modules'
$base0 = @(Get-ChildItem -LiteralPath $nmApp -Force).Count
$base1 = @(Get-ChildItem -LiteralPath $nmCli -Force).Count
Write-Output "BASELINE base=$Base@$($baseSha.Substring(0,10)) tree=$baseTree app/node_modules=$base0 app/render-cli/node_modules=$base1"
if ($base0 -eq 0 -or $base1 -eq 0) { Write-Output 'FAILED:wt-teardown primary node_modules already empty'; exit 1 }

# Printing happens HERE, at the call site, never inside the predicate -- see the comment on
# Test-PrimaryHealthy for the dead-guard this arrangement exists to prevent.
function Assert-Primary {
  param([string]$Stage)
  $s = Test-PrimaryHealthy -Repo $Repo -ExpectApp $base0 -ExpectCli $base1
  Write-Output "    PRIMARY $Stage tsc=$($s.Tsc) app=$($s.App)/$base0 cli=$($s.Cli)/$base1 ok=$($s.Ok)"
  if (-not $s.Ok) { Write-Output "FAILED:wt-teardown primary damaged at $Stage"; exit 1 }
}

# worktree -> branch
$wtBranch = @{}
$cur = $null
foreach ($line in @(& git -C $Repo worktree list --porcelain)) {
  $line = "$line"
  if ($line -like 'worktree *') { $cur = $line.Substring(9).Trim() }
  elseif ($line -like 'branch *') { $wtBranch[$cur] = $line.Substring(7).Trim() -replace '^refs/heads/', '' }
}

$targets = @()
foreach ($d in (Get-ChildItem -LiteralPath $Pool -Directory | Sort-Object Name)) {
  if ($d.CreationTime -lt $CohortStart -or $d.CreationTime -gt $CohortEnd) { continue }
  $br = $wtBranch[($d.FullName -replace '\\', '/')]
  if (-not $br) { continue }
  $targets += [pscustomobject]@{ Path = $d.FullName; Name = $d.Name; Branch = $br }
}
Write-Output "CANDIDATES $($targets.Count)"

$done = 0; $skipped = @()
foreach ($t in $targets) {
  if ($Limit -gt 0 -and $done -ge $Limit) { break }
  Write-Output "--- $($t.Name) [$($t.Branch)]"

  # RECEIPT, re-verified immediately before acting. `git branch -d` cannot protect us here
  # (a squash-merged branch is not an ancestor, so -d refuses it and -D is required, which
  # disables git's own safety net) -- this check is the replacement for that net.
  $rcpt = Test-BranchLanded -Repo $Repo -Branch $t.Branch -BaseSha $baseSha -BaseTree $baseTree
  if (-not $rcpt.Landed) {
    Write-Output "    SKIP not landed (method=$($rcpt.Method) added=$($rcpt.Added) residual=$($rcpt.Residual))"
    $skipped += "$($t.Name)/$($t.Branch) residual=$($rcpt.Residual)"; continue
  }

  $dirty = @(& git -C $t.Path status --porcelain 2>&1)
  if ($dirty.Count -gt 0) { Write-Output "    SKIP dirty ($($dirty.Count) entries)"; $skipped += $t.Name; continue }

  $sha = "$(@(& git -C $Repo rev-parse $t.Branch)[0])".Trim()
  Write-Output "    receipt=$($rcpt.Method) added=$($rcpt.Added) residual=$($rcpt.Residual) sha=$sha"
  if ($WhatIf) { Write-Output '    WHATIF would unlink + remove worktree + delete branch'; $done++; continue }

  # 1. unlink the junctions (prepare-worktree asserts the primary survived and exits 1 if not)
  $u = @(& pwsh -NoProfile -File $prep -Worktree $t.Path -Unlink 2>&1)
  if ($LASTEXITCODE -ne 0 -or -not ($u -match 'SUCCESS:prepare-worktree unlinked')) {
    Write-Output "    ABORT unlink failed: $($u -join ' | ')"; exit 1
  }
  Assert-Primary 'after-unlink'

  # 2. let git remove the worktree (never a recursive delete of the directory)
  $rm = @(& git -C $Repo worktree remove $t.Path 2>&1)
  if ($LASTEXITCODE -ne 0) {
    Write-Output "    remove returned: $($rm -join ' | ')"

    # MEASURED 2026-08-08 on agent-612289141, after 17 consecutive clean removals: git
    # reports "Permission denied" having ALREADY deregistered the worktree and emptied the
    # directory -- only the (now empty) directory handle was still locked, transiently, by
    # something outside git. Retrying with --force then fails with "is not a working tree",
    # because there is no longer a working tree to force. So the intermittent lock is not
    # systematic and must not abort the run; detect the already-deregistered state and
    # finish the one remaining step ourselves.
    $stillRegistered = [bool](@(& git -C $Repo worktree list --porcelain) -match [regex]::Escape(($t.Path -replace '\\', '/')))
    if ($stillRegistered) {
      $rm = @(& git -C $Repo worktree remove --force $t.Path 2>&1)
      if ($LASTEXITCODE -ne 0) { Write-Output "    ABORT worktree remove failed: $($rm -join ' | ')"; exit 1 }
    }
    else {
      # Deregistered already. Removing the leftover directory is only safe once we have
      # positively confirmed it holds nothing and carries no junction -- otherwise this
      # would be the recursive delete the whole script exists to avoid.
      foreach ($rel in @('app\node_modules', 'app\render-cli\node_modules')) {
        if (Test-Path -LiteralPath (Join-Path $t.Path $rel)) { Write-Output "    ABORT junction still present: $rel"; exit 1 }
      }
      $left = @(Get-ChildItem -LiteralPath $t.Path -Force -Recurse -ErrorAction SilentlyContinue)
      if ($left.Count -ne 0) { Write-Output "    ABORT deregistered but $($left.Count) file(s) remain; not deleting"; exit 1 }
      Remove-Item -LiteralPath $t.Path -Force -Recurse -ErrorAction SilentlyContinue
      Write-Output "    recovered: empty deregistered directory removed (dir-gone=$(-not (Test-Path -LiteralPath $t.Path)))"
    }
  }
  Assert-Primary 'after-remove'

  # 3. delete the branch. -D is required (see above); the SHA is printed so it is recoverable.
  $bd = @(& git -C $Repo branch -D $t.Branch 2>&1)
  if ($LASTEXITCODE -ne 0) { Write-Output "    WARN branch delete failed: $($bd -join ' | ')" }
  else { Write-Output "    deleted branch $($t.Branch) (was $sha)" }

  $done++
}

Write-Output "SUCCESS:wt-teardown processed=$done skipped=$($skipped.Count) [$($skipped -join ', ')]"
exit 0
