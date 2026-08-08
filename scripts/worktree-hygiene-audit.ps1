<#
.SYNOPSIS
  Assert the agent-worktree pool holds no leftover, fully-landed programme worktrees.

.DESCRIPTION
  A fan-out programme leaves one git worktree + one fix/* branch per work unit. Once the
  work has landed on main those worktrees are pure cost: each one pins a branch ref, holds
  two junctions into the primary checkout's dependency trees, and hides genuinely unmerged
  work in the noise. This script is the regression guard that says "the pool is clean".

  READ-ONLY. It never deletes anything; scripts/worktree-hygiene-teardown.ps1 does that.

  WHY NOT `git merge-base --is-ancestor`
  This repo squash-merges. A squash-merged branch is NOT an ancestor of main -- its
  commits never enter main's history, only their combined content does. Ancestry therefore
  reports a fully-landed branch as unmerged. This script uses CONTENT containment instead:
  `git merge-tree --write-tree <base> <branch>` produces the tree that merging would yield;
  if that equals <base>'s own tree, the branch contributes nothing and its work has landed.

  WHY NOT `gh pr list --head <branch>`
  Measured on this repo 2026-08-08: zero of the 24 programme branches was ever pushed
  (`git branch -r --list origin/fix/*` returns 16 branches, all pre-programme). An empty
  gh result here means "never pushed", NOT "not merged" -- using it as the receipt would
  have classified all 24 as unmerged.

  DETECTOR SELF-VALIDATION (the both-states test)
  A containment probe that answers "contained" for everything is indistinguishable from a
  probe that is broken. Before classifying anything this script proves its detector can
  produce BOTH answers:
    positive -- merging an ancestor (main~1) must yield exactly main's tree;
    negative -- at least one real branch in the repo must NOT yield main's tree.
  If either control fails the script aborts and classifies nothing. This is not theatre:
  an earlier revision of this probe read `$t[0]` on git's output, which returns the first
  CHARACTER when git emits a single line, and every branch on earth compared not-equal.
  The tell was a self-contradiction -- a branch with a merged-PR receipt reporting
  un-contained. Hence @() around every git capture below.

.PARAMETER Repo
  The primary checkout that owns the shared .git and the worktree admin data.

.PARAMETER Pool
  Directory holding the agent worktrees.

.PARAMETER CohortStart / .PARAMETER CohortEnd
  Only worktrees CREATED inside this window are in scope. This is the guard that keeps
  unrelated agent worktrees -- including ones created later that hold untracked work --
  out of a teardown. Do NOT replace it with a name pattern: every worktree in the pool
  matches `agent-*`, so a name glob would sweep up live siblings.

.PARAMETER Base
  Ref to test containment against. Defaults to origin/main (the current published head)
  and falls back to main when there is no remote-tracking ref.
#>
[CmdletBinding()]
param(
  [string]$Repo = 'C:\Users\Prekzursil\Documents\GitHub\Reframe',
  [string]$Pool = 'C:\Users\Prekzursil\.claude\agent-worktrees',
  [datetime]$CohortStart = '2026-07-31 23:00',
  [datetime]$CohortEnd = '2026-08-01 01:00',
  [string]$Base = ''
)

$ErrorActionPreference = 'Stop'

# Every call site wraps this in @(). PowerShell UNROLLS a single-element array on return,
# so a bare `Get-GitLine ...` that produced one line hands back a [string], and indexing [0]
# on it yields a [char]. Same family as the $t[0] bug described in the header.
#
# Named Get-GitLine, not Git-Lines: `Git` is not an approved PowerShell verb (PSSA
# PSUseApprovedVerbs) and the noun is singular by convention (PSUseSingularNouns). More
# importantly the name must not be `git` in any casing -- command resolution is
# case-insensitive and prefers functions over applications, so a helper called `Git` makes
# the `& git` inside its own body call itself. That recursion cost a 600s hang in this
# lane's self-test before it was diagnosed.
function Get-GitLine { param([string[]]$GitArgs) return @(& git -C $Repo @GitArgs 2>&1) }

if (-not (Test-Path -LiteralPath $Repo)) { Write-Output "FAILED:wt-hygiene repo not found: $Repo"; exit 1 }

. (Join-Path $PSScriptRoot 'lib\branch-containment.ps1')

# Pin to an immutable SHA. Passing the moving ref `origin/main` to each probe made 14
# branches flip mid-run while Dependabot merges landed -- see the lib header.
if (-not $Base) { $Base = 'origin/main' }
$baseSha = Get-BaseSha -Repo $Repo -Ref $Base
if (-not $baseSha) { Write-Output "FAILED:wt-hygiene cannot resolve $Base"; exit 1 }
$baseTree = Get-TreeOf -Repo $Repo -Rev $baseSha

function Test-Contained {
  param([string]$Ref)
  return (Test-BranchLanded -Repo $Repo -Branch $Ref -BaseSha $baseSha -BaseTree $baseTree).Landed
}

# ---------------------------------------------------------------- detector controls
$posOk = Test-Contained "$baseSha~1"
$negRef = $null
foreach ($b in @(Get-GitLine @('for-each-ref', 'refs/heads/', '--format=%(refname:short)'))) {
  $b = "$b".Trim(); if (-not $b) { continue }
  if (-not (Test-Contained $b)) { $negRef = $b; break }
}
Write-Output "DETECTOR base=$Base@$($baseSha.Substring(0,10)) tree=$baseTree positive-control=$posOk negative-control=$negRef"
if (-not $posOk) { Write-Output 'FAILED:wt-hygiene detector positive control failed (an ancestor must be contained)'; exit 1 }
if (-not $negRef) { Write-Output 'FAILED:wt-hygiene detector negative control failed (no branch is un-contained; probe cannot discriminate)'; exit 1 }

# ---------------------------------------------------------------- worktree -> branch map
$wtBranch = @{}
$cur = $null
foreach ($line in @(Get-GitLine @('worktree', 'list', '--porcelain'))) {
  $line = "$line"
  if ($line -like 'worktree *') { $cur = $line.Substring(9).Trim() }
  elseif ($line -like 'branch *') { $wtBranch[$cur] = $line.Substring(7).Trim() -replace '^refs/heads/', '' }
}

# ---------------------------------------------------------------- classify the pool
$violations = @()
$kept = @()
if (Test-Path -LiteralPath $Pool) {
  foreach ($d in (Get-ChildItem -LiteralPath $Pool -Directory | Sort-Object Name)) {
    if ($d.CreationTime -lt $CohortStart -or $d.CreationTime -gt $CohortEnd) { continue }  # not this programme
    $br = $wtBranch[($d.FullName -replace '\\', '/')]
    if (-not $br) { continue }                                                             # detached => not a programme unit
    if (Test-Contained $br) { $violations += "$($d.Name) [$br]" }
    else { $kept += "$($d.Name) [$br] -- NOT contained in $Base; holds unique work" }
  }
}

foreach ($k in $kept) { Write-Output "KEEP      $k" }
foreach ($v in $violations) { Write-Output "VIOLATION $v -- fully landed in $Base, worktree still present" }

if ($violations.Count -gt 0) {
  Write-Output "FAILED:wt-hygiene $($violations.Count) landed programme worktree(s) still in the pool; $($kept.Count) correctly kept"
  exit 1
}
Write-Output "SUCCESS:wt-hygiene pool clean; 0 landed programme worktrees, $($kept.Count) kept for unique work"
exit 0
