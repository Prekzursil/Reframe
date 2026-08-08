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
    Tier 2 -- line-set containment. For every file the branch changed, take the lines it
      ADDED relative to its own merge-base and test membership in the base's blob. Set
      membership cannot conflict, so it stays decisive as the base advances.
  Dropping tier 2 is not a conservative simplification: it converts branches whose work
  demonstrably landed into permanent false keeps, because a long-lived base eventually
  conflicts with everything.

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

function Test-BranchLanded {
  <#
    Returns [pscustomobject] @{ Landed; Method; Residual; Added }
    Method: tree-equal | line-containment | not-landed | error
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
    return [pscustomobject]@{ Landed = $true; Method = 'tree-equal'; Residual = 0; Added = 0 }
  }

  # ---- tier 2: line-set containment against the base's blobs.
  $mb = "$(@(& git -C $Repo merge-base $BaseSha $Branch)[0])".Trim()
  if (-not $mb) { return [pscustomobject]@{ Landed = $false; Method = 'error'; Residual = -1; Added = 0 } }

  $added = 0; $residual = 0
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

    foreach ($l in $bLines) {
      $s = "$l"
      if ($wasSet.Contains($s)) { continue }                    # not introduced by this branch
      $added++
      if ($absentInBase -or -not $tgtSet.Contains($s)) { $residual++ }
    }
  }

  if ($added -gt 0 -and $residual -eq 0) {
    return [pscustomobject]@{ Landed = $true; Method = 'line-containment'; Residual = 0; Added = $added }
  }
  return [pscustomobject]@{ Landed = $false; Method = 'not-landed'; Residual = $residual; Added = $added }
}
