<#
.SYNOPSIS
  Make a fresh git worktree able to run the local gate (tsc / vitest / pre-commit).

.DESCRIPTION
  `git worktree add` checks out tracked files ONLY, so a new worktree has NO
  app/node_modules and every `npx tsc` / `npx vitest` there fails with missing
  modules. Rather than a multi-minute `npm ci` per worktree, this junctions the
  dependency trees from the primary checkout.

  WHY A JUNCTION AND NOT A COPY: app/node_modules is ~243 top-level packages and
  hundreds of MB. Parallel implementer worktrees only READ it.

  KNOWN HAZARD THIS SCRIPT EXISTS TO CONTAIN — a junction is a reparse point, and a
  naive `Remove-Item -Recurse -Force <worktree>` can delete THROUGH it and destroy the
  primary checkout's node_modules, breaking every build on the machine. Measured on
  this repo: three orphaned worktrees each held
    <wt>/app/node_modules -> C:/.../Reframe/app/node_modules
  and `git worktree remove` refused them with "Invalid argument" precisely because of
  those links. ALWAYS tear down with -Unlink (below), never with a bare recursive
  delete.

  Concurrency note, stated honestly: parallel vitest runs sharing ONE junctioned
  node_modules also share node_modules/.vite. That cache is content-addressed and
  read-mostly, but it is a shared mutable path, so a flake under heavy fan-out is
  possible. If it bites, drop to -NoVite (sets VITE_CACHE_DIR per worktree).

.PARAMETER Worktree
  Path to the worktree to prepare (or tear down).

.PARAMETER Primary
  The primary checkout that owns the real dependency trees.

.PARAMETER Unlink
  Remove ONLY the junctions this script created, leaving the worktree intact and the
  primary untouched. Run this before `git worktree remove`.

.EXAMPLE
  pwsh -File scripts/prepare-worktree.ps1 -Worktree C:\wt\fix-a
  pwsh -File scripts/prepare-worktree.ps1 -Worktree C:\wt\fix-a -Unlink
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Worktree,
  [string]$Primary = 'C:\Users\Prekzursil\Documents\GitHub\Reframe',
  [switch]$Unlink,
  [switch]$NoVite
)

$ErrorActionPreference = 'Stop'

# Relative dependency trees a worktree needs to run tsc + vitest. Kept minimal on
# purpose: packaging inputs (build/ffmpeg, build/python-embed-314) are NOT linked,
# because the unit gate does not need them and linking more widens the blast radius.
$LINKS = @(
  'app/node_modules',
  'app/render-cli/node_modules'
)

function Resolve-Full([string]$p) { return [System.IO.Path]::GetFullPath($p) }

$wt = Resolve-Full $Worktree
$pr = Resolve-Full $Primary

if (-not (Test-Path -LiteralPath $wt)) { Write-Output "FAILED:prepare-worktree worktree not found: $wt"; exit 1 }

if ($Unlink) {
  foreach ($rel in $LINKS) {
    $link = Join-Path $wt ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $link)) { continue }
    $info = Get-Item -LiteralPath $link -Force
    if (-not $info.LinkType) {
      # A REAL directory, not our junction — never touch it.
      Write-Output "  skip (real dir, not a link): $link"
      continue
    }
    # Directory.Delete(path, recursive:$false) on a reparse point removes the LINK
    # and leaves the target alone. This is the only safe teardown.
    [System.IO.Directory]::Delete($link, $false)
    Write-Output "  unlinked: $link"
  }
  # Prove the primary survived — the whole point of the -Unlink path.
  $realNm = Join-Path $pr 'app\node_modules'
  $ok = Test-Path -LiteralPath $realNm
  $n = if ($ok) { @(Get-ChildItem -LiteralPath $realNm -ErrorAction SilentlyContinue).Count } else { 0 }
  Write-Output "  primary app/node_modules intact=$ok items=$n"
  if (-not $ok -or $n -eq 0) { Write-Output 'FAILED:prepare-worktree primary node_modules damaged'; exit 1 }
  Write-Output 'SUCCESS:prepare-worktree unlinked'
  exit 0
}

foreach ($rel in $LINKS) {
  $src = Join-Path $pr ($rel -replace '/', '\')
  $dst = Join-Path $wt ($rel -replace '/', '\')
  if (-not (Test-Path -LiteralPath $src)) { Write-Output "  skip (absent in primary): $rel"; continue }
  if (Test-Path -LiteralPath $dst) {
    $existing = Get-Item -LiteralPath $dst -Force
    if ($existing.LinkType) { Write-Output "  already linked: $rel"; continue }
    Write-Output "  skip (real dir present): $rel"
    continue
  }
  $parent = Split-Path -Parent $dst
  if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
  Write-Output "  junction: $rel -> $src"
}

if ($NoVite) {
  # Per-worktree vite cache, for when the shared one is suspected of flaking.
  $cache = Join-Path $wt '.vite-cache'
  if (-not (Test-Path -LiteralPath $cache)) { New-Item -ItemType Directory -Path $cache -Force | Out-Null }
  Write-Output "  VITE_CACHE_DIR=$cache  (export this before running vitest)"
}

# Verify the worktree can actually resolve a dependency — a junction that exists but
# does not resolve is the failure this check exists to catch.
$probe = Join-Path $wt 'app\node_modules\typescript\package.json'
if (Test-Path -LiteralPath $probe) {
  Write-Output '  verified: typescript resolves through the junction'
  Write-Output 'SUCCESS:prepare-worktree'
  exit 0
}
Write-Output "FAILED:prepare-worktree typescript did not resolve at $probe"
exit 1
