<#
.SYNOPSIS
  Shared "has this branch's work landed?" receipt, used by worktree-hygiene-{audit,teardown}.

.DESCRIPTION
  WHY THIS IS NOT `git merge-base --is-ancestor`
  This repo squash-merges, so a fully-landed branch is NOT an ancestor of main -- only its
  combined content is. Ancestry reports every landed branch as unmerged.

  WHY THIS IS NOT `gh pr list --head <branch>`
  Measured 2026-08-08: zero of the 24 programme branches was ever pushed. An empty gh
  result means "never pushed", not "not merged".

  TWO TIERS, because one probe is not enough.
    Tier 1 -- tree equality. `git merge-tree --write-tree <baseSha> <branch>`; if the
      resulting tree equals the base's own tree, merging changes nothing, so the branch
      contributes nothing. Fast and exact, but returns CONFLICT (indeterminate, not
      "unmerged") whenever the base later touched the same regions.
    Tier 2 -- CONTEXT-WINDOW containment. For every file the branch changed, take the lines
      it ADDED relative to its own merge-base and require each one to appear in the base's
      blob *together with its two neighbours*. Membership cannot conflict, so it stays
      decisive as the base advances.
  Dropping tier 2 is not a conservative simplification: it converts branches whose work
  demonstrably landed into permanent false keeps, because a long-lived base eventually
  conflicts with everything.

  WHY THE WINDOW, NOT BARE SET MEMBERSHIP. The first version tested each added line for
  membership in a HashSet of the target's lines -- position-blind. Source code is full of
  lines that recur verbatim (`}`, `  return None`, `    })`, an import), so a branch whose
  additions happen to be individually common scores residual=0 and is declared LANDED while
  none of its work is present. `Landed` is what authorises `git branch -D` in
  worktree-hygiene-teardown.ps1, so that error class deletes unlanded work. Requiring the
  (previous, line, next) triple shifts every coincidence to needing three consecutive lines
  to coincide, which effectively does not happen; and when the branch's work landed in a
  MODIFIED form the window misses and the verdict becomes not-landed -- i.e. the errors now
  point at KEEPING a branch rather than deleting one. `Residual` (window) and `WeakResidual`
  (bare membership, the old measure) are both returned so the gap between them is visible
  instead of inferred.

  MEASURED LIMITATION, inline rather than in a footnote: tier 2 considers ADDED lines only.
  A branch whose contribution was a DELETION that never landed would be reported as landed.
  Settle that case for a specific branch with `git diff <mergeBase> <branch> --diff-filter=D`
  plus a check that the base still carries the file. Not automated here because every unit
  in this programme was additive; do not reuse this on a deletion-heavy branch without
  closing that gap.

  PIN THE BASE TO A SHA, NEVER A MOVING REF. Measured 2026-08-08: passing the ref
  `origin/main` while Dependabot merges landed mid-run made 14 branches flip from contained
  to not-contained inside one loop -- the captured base tree no longer matched the tree the
  re-resolved ref produced. Get-BaseSha exists so callers cannot make that mistake.
#>

function Test-PrimaryHealthy {
  <#
    Pure predicate for "the primary checkout's dependency trees are undamaged".

    IT IS A PURE PREDICATE ON PURPOSE. The first version of this guard lived inline in
    worktree-hygiene-teardown.ps1 and did `Write-Output "..."` and then `return $ok` in the
    same function. PowerShell adds BOTH to the output stream, so the caller's
    `if (-not (Test-PrimaryIntact ...))` tested a two-element array -- which is always
    truthy -- and the guard could never fire. It was a dead safety check that read as a
    live one. Keep printing at the CALL SITE; this function returns one object and nothing
    else, so `-not $result.Ok` cannot be fooled.

    Returns [pscustomobject] @{ App; Cli; Tsc; Ok }
  #>
  param(
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][int]$ExpectApp,
    [Parameter(Mandatory)][int]$ExpectCli
  )
  $nmApp = Join-Path $Repo 'app\node_modules'
  $nmCli = Join-Path $Repo 'app\render-cli\node_modules'
  $a = @(Get-ChildItem -LiteralPath $nmApp -Force -ErrorAction SilentlyContinue).Count
  $c = @(Get-ChildItem -LiteralPath $nmCli -Force -ErrorAction SilentlyContinue).Count
  $t = Test-Path -LiteralPath (Join-Path $nmApp '.bin\tsc')
  # Counts may only ever be >= baseline: a concurrent npm install can legitimately add a
  # package, but nothing this script does may ever REMOVE one.
  return [pscustomobject]@{ App = $a; Cli = $c; Tsc = $t; Ok = ($a -ge $ExpectApp -and $c -ge $ExpectCli -and $t) }
}

function Get-BaseSha {
  param([Parameter(Mandatory)][string]$Repo, [string]$Ref = 'origin/main')
  $sha = "$(@(& git -C $Repo rev-parse --verify --quiet $Ref)[0])".Trim()
  if (-not $sha) { $sha = "$(@(& git -C $Repo rev-parse --verify --quiet 'main')[0])".Trim() }
  return $sha
}

function Get-TreeOf {
  param([Parameter(Mandatory)][string]$Repo, [Parameter(Mandatory)][string]$Rev)
  # `show -s --format=%T` avoids the `<rev>^{tree}` peel syntax; `^` is PowerShell's escape
  # character and corrupts a ref on some invocation paths.
  return "$(@(& git -C $Repo show -s --format=%T $Rev)[0])".Trim()
}

function Get-ContextWindows {
  <#
    The set of (previous, line, next) triples in a file, joined by a delimiter that cannot
    occur in source text. Missing neighbours at the file edges are the empty string, so the
    first and last lines are still representable.
  #>
  param([string[]]$Lines)
  $set = [System.Collections.Generic.HashSet[string]]::new()
  for ($i = 0; $i -lt $Lines.Count; $i++) {
    $prev = if ($i -gt 0) { "$($Lines[$i - 1])" } else { '' }
    $next = if ($i -lt $Lines.Count - 1) { "$($Lines[$i + 1])" } else { '' }
    [void]$set.Add("$prev`u{0000}$($Lines[$i])`u{0000}$next")
  }
  return $set
}

function Test-BranchLanded {
  <#
    Returns [pscustomobject] @{ Landed; Method; Residual; WeakResidual; Added }
    Method: tree-equal | context-containment | not-landed | error

    Residual     -- added lines whose (prev,line,next) window is absent from the base. This
                    is the one `Landed` depends on.
    WeakResidual -- added lines whose TEXT is absent from the base anywhere. Kept only as a
                    diagnostic: WeakResidual=0 with Residual>0 is precisely the
                    coincidental-line-match case the old predicate mistook for landed.
  #>
  param(
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Branch,
    [Parameter(Mandatory)][string]$BaseSha,
    [Parameter(Mandatory)][string]$BaseTree
  )

  # ---- tier 1: tree equality.
  # @() is mandatory: git emitting a single line hands back a [string], and indexing [0]
  # on a string returns a [char], which compares unequal to every SHA on earth.
  $mt = @(& git -C $Repo merge-tree --write-tree $BaseSha $Branch 2>&1)
  if ($LASTEXITCODE -eq 0 -and "$($mt[0])".Trim() -eq $BaseTree) {
    return [pscustomobject]@{ Landed = $true; Method = 'tree-equal'; Residual = 0; WeakResidual = 0; Added = 0 }
  }

  # ---- tier 2: context-window containment against the base's blobs.
  $mb = "$(@(& git -C $Repo merge-base $BaseSha $Branch)[0])".Trim()
  if (-not $mb) {
    return [pscustomobject]@{ Landed = $false; Method = 'error'; Residual = -1; WeakResidual = -1; Added = 0 }
  }

  $added = 0; $residual = 0; $weakResidual = 0
  foreach ($f in @(& git -C $Repo diff --name-only $mb $Branch 2>$null)) {
    $f = "$f".Trim(); if (-not $f) { continue }

    $bLines = @(& git -C $Repo show "${Branch}:$f" 2>$null)
    if ($LASTEXITCODE -ne 0) { continue }                       # deleted on branch -- see limitation above
    $baseLines = @(& git -C $Repo show "${mb}:$f" 2>$null)
    if ($LASTEXITCODE -ne 0) { $baseLines = @() }
    $tgtLines = @(& git -C $Repo show "${BaseSha}:$f" 2>$null)
    $absentInBase = ($LASTEXITCODE -ne 0)

    $wasSet = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($l in $baseLines) { [void]$wasSet.Add("$l") }
    $tgtSet = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($l in $tgtLines) { [void]$tgtSet.Add("$l") }
    $tgtWindows = Get-ContextWindows -Lines $tgtLines

    for ($i = 0; $i -lt $bLines.Count; $i++) {
      $s = "$($bLines[$i])"
      if ($wasSet.Contains($s)) { continue }                    # not introduced by this branch
      $added++
      if ($absentInBase) { $residual++; $weakResidual++; continue }
      if (-not $tgtSet.Contains($s)) { $weakResidual++ }
      $prev = if ($i -gt 0) { "$($bLines[$i - 1])" } else { '' }
      $next = if ($i -lt $bLines.Count - 1) { "$($bLines[$i + 1])" } else { '' }
      if (-not $tgtWindows.Contains("$prev`u{0000}$s`u{0000}$next")) { $residual++ }
    }
  }

  if ($added -gt 0 -and $residual -eq 0) {
    return [pscustomobject]@{
      Landed = $true; Method = 'context-containment'; Residual = 0; WeakResidual = $weakResidual; Added = $added
    }
  }
  return [pscustomobject]@{
    Landed = $false; Method = 'not-landed'; Residual = $residual; WeakResidual = $weakResidual; Added = $added
  }
}
