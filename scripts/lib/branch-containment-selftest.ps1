<#
.SYNOPSIS
  Both-states proof for Test-BranchLanded, on a throwaway fixture repo.

.DESCRIPTION
  `Landed = $true` is what authorises `git branch -D` in worktree-hygiene-teardown.ps1, so
  the predicate needs a proof that it says NO in the case that matters, not only YES on a
  branch that really landed. A verdict that has only ever been observed agreeing is
  indistinguishable from a verdict that always agrees (single-signal-verification 3b).

  Four cases, built from scratch in a temp repo so nothing depends on this checkout's state:

    C1 landed-verbatim      branch content present in base as a contiguous block -> LANDED
    C2 coincidental-lines   every added line occurs SOMEWHERE in base, but never as a block.
                            This is the false-positive the position-blind predicate shipped
                            with: bare set membership scores residual=0 and deletes work that
                            never landed. Must be NOT LANDED, and WeakResidual must be 0 --
                            that gap (weak=0, strict>0) IS the bug, made visible.
    C3 genuinely-unlanded   added lines absent from base entirely -> NOT LANDED
    C4 tree-equal           branch adds nothing -> LANDED via tier 1, without reaching tier 2

.NOTES
  Run:  pwsh -NoProfile -File scripts/lib/branch-containment-selftest.ps1
  Exit 0 when all four behave; 1 otherwise, naming the case.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'branch-containment.ps1')

$root = Join-Path ([System.IO.Path]::GetTempPath()) "bc-selftest-$([guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Path $root | Out-Null

# The git EXECUTABLE, resolved once and called by absolute path.
#
# Do NOT wrap this in a helper named `Git`, and do not `Set-Alias Git <helper>`: PowerShell
# command resolution is case-INSENSITIVE and puts aliases and functions ahead of
# applications, so `& git ...` inside such a helper resolves back to the helper. The first
# version of this file did exactly that and recursed forever -- 600s with zero bytes on
# stdout and stderr, which reads like an environment problem rather than a bug in the script.
# A trivial control script launched the same way finished in under a second, which is what
# localised it here.
$gitExe = (Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
if (-not $gitExe) { throw 'git.exe not found on PATH' }

function Invoke-FixtureGit {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
  & $gitExe -C $root @GitArgs 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "fixture git failed ($LASTEXITCODE): git $($GitArgs -join ' ')" }
}

function Write-FixtureFile {
  param([string]$Name, [string[]]$Lines)
  Set-Content -LiteralPath (Join-Path $root $Name) -Value ($Lines -join "`n") -Encoding utf8NoBOM -NoNewline
}

$ANCESTOR = @('def a():', '    x = 1', '    return x', '', 'def b():', '    y = 2', '    return y')

try {
  Invoke-FixtureGit init -q -b main
  Invoke-FixtureGit config user.email 'selftest@example.invalid'
  Invoke-FixtureGit config user.name 'selftest'
  Invoke-FixtureGit config commit.gpgsign false

  # ---- the shared ancestor -------------------------------------------------
  Write-FixtureFile 'mod.py' $ANCESTOR
  Invoke-FixtureGit add -A
  Invoke-FixtureGit commit -q -m base0

  # C2: the SAME three lines the base will later gain, but in a different ORDER. Each one is
  # therefore individually present in the base (weakResidual=0) while the arrangement this
  # branch actually wrote never landed anywhere (residual=3). Getting this fixture wrong is
  # easy -- the first attempt used a line the base never gains, so weakResidual was 1 and the
  # case would have passed without exercising coincidence at all. The in-loop fixture
  # assertion below exists because that mistake was made here, and caught, rather than
  # shipped.
  Invoke-FixtureGit checkout -q -b coincidental
  Write-FixtureFile 'mod.py' ($ANCESTOR + @('', 'def real():', '    return z', '    z = 3'))
  Invoke-FixtureGit add -A
  Invoke-FixtureGit commit -q -m coincidental

  Invoke-FixtureGit checkout -q main
  Invoke-FixtureGit checkout -q -b unlanded
  Write-FixtureFile 'mod.py' ($ANCESTOR + @('', 'def totally_new():', '    return "nothing like this exists"'))
  Invoke-FixtureGit add -A
  Invoke-FixtureGit commit -q -m unlanded

  Invoke-FixtureGit checkout -q main
  Invoke-FixtureGit checkout -q -b landed
  Write-FixtureFile 'mod.py' ($ANCESTOR + @('', 'def real():', '    z = 3', '    return z'))
  Invoke-FixtureGit add -A
  Invoke-FixtureGit commit -q -m landed

  Invoke-FixtureGit checkout -q main
  Invoke-FixtureGit checkout -q -b noop   # C4: identical content -> merge-tree equals base tree

  # ---- advance the base: the `landed` branch's block really lands ----------
  # It lands together with a FURTHER function appended in the same region, so a three-way
  # merge of `landed` into the base conflicts and tier 1 cannot answer. That is deliberate:
  # tier 2 is the code under test, and a fixture where every positive case short-circuits at
  # tree-equality would leave context-containment with no passing case at all -- the same
  # "green but never executed" hole this whole file exists to close. (Measured: with the base
  # gaining ONLY the branch's own block, C1 returned method=tree-equal, added=0.)
  Invoke-FixtureGit checkout -q main
  Write-FixtureFile 'mod.py' ($ANCESTOR + @(
      '', 'def real():', '    z = 3', '    return z',
      '', 'def extra():', '    return 0'))
  Invoke-FixtureGit add -A
  Invoke-FixtureGit commit -q -m 'base advances, absorbing the landed work and appending more'

  $baseSha = "$(@(& $gitExe -C $root rev-parse HEAD)[0])".Trim()
  $baseTree = Get-TreeOf -Repo $root -Rev $baseSha

  # ExpectMethod is asserted too, not just the verdict: C1 passing via `tree-equal` would be
  # the right answer from the wrong code path and would leave tier 2 unexercised.
  $cases = @(
    @{ Name = 'C1 landed-verbatim'; Branch = 'landed'; Expect = $true; ExpectMethod = 'context-containment' },
    @{ Name = 'C2 coincidental-lines'; Branch = 'coincidental'; Expect = $false; ExpectMethod = 'not-landed' },
    @{ Name = 'C3 genuinely-unlanded'; Branch = 'unlanded'; Expect = $false; ExpectMethod = 'not-landed' },
    @{ Name = 'C4 tree-equal'; Branch = 'noop'; Expect = $true; ExpectMethod = 'tree-equal' }
  )

  $failures = @()
  foreach ($c in $cases) {
    $r = Test-BranchLanded -Repo $root -Branch $c.Branch -BaseSha $baseSha -BaseTree $baseTree
    $ok = ($r.Landed -eq $c.Expect) -and ($r.Method -eq $c.ExpectMethod)
    $mark = if ($ok) { 'OK  ' } else { 'FAIL' }
    Write-Output ("  {0} {1,-24} landed={2,-5} method={3,-20} added={4} residual={5} weakResidual={6}" -f `
        $mark, $c.Name, $r.Landed, $r.Method, $r.Added, $r.Residual, $r.WeakResidual)
    if (-not $ok) { $failures += $c.Name }

    # C2 is the whole point: assert the SHAPE of the bug, not just the verdict. If
    # WeakResidual stops being 0 the fixture no longer exercises coincidental matching and
    # the case would pass for the wrong reason -- a green test measuring nothing.
    if ($c.Name -like 'C2*') {
      if ($r.WeakResidual -ne 0) {
        Write-Output "  FAIL C2 fixture no longer exercises coincidence (weakResidual=$($r.WeakResidual), expected 0)"
        $failures += 'C2-fixture'
      }
      if ($r.Residual -le 0) {
        Write-Output "  FAIL C2 window check did not fire (residual=$($r.Residual), expected > 0)"
        $failures += 'C2-window'
      }
    }
  }

  if ($failures.Count) {
    Write-Output "FAILED:bc-selftest $($failures.Count) case(s): $($failures -join ', ')"
    exit 1
  }
  Write-Output ("SUCCESS:bc-selftest {0}/{0} cases behaved; C2 proves the position-blind predicate would have deleted unlanded work" -f $cases.Count)
  exit 0
}
finally {
  # Bounded by construction: this fixture holds no junctions and nothing outside $root --
  # unlike the teardown script's tree, which is why that one refuses to recurse until it has
  # proved the directory is empty.
  Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
