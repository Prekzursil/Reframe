<#
.SYNOPSIS
  Compile-check build/installer.nsh (the WU-I1 NSIS component page) with the REAL
  makensis, without running a full electron-builder packaging pass.

.DESCRIPTION
  installer.nsh is a text file until makensis parses it. Nothing in the 6-gate quality
  charter can see inside it: gate:1 skips `build/` (.pre-commit-config.yaml `exclude`),
  gate:2 is tsc/basedpyright, and the vitest conformance test in
  app/main/installerSeed.test.ts only pins its IDS AND LABELS against
  app/main/installProfiles.ts — it cannot tell an unbalanced ${If} from a valid one.
  So a syntax error here would surface only when a human runs a Windows build.

  This script closes that gap locally. It synthesises the minimum electron-builder
  context installer.nsh expects (MUI2 + LogicLib + nsDialogs, an install Section, a
  page slot), inserts BOTH exported macros in the same positions app-builder-lib does
  (templates/nsis/assistedInstaller.nsh:42 and templates/nsis/installSection.nsh:81),
  and compiles. It asserts nothing about the produced installer — only that the code
  we ship is syntactically valid NSIS.

  NOT a CI gate: makensis is a Windows binary that arrives with electron-builder's own
  download cache, and the `quality` workflow runs on Linux. Adding a gate would also
  breach QUALITY-CHARTER.md rule 2 (the gate list is closed). Run it by hand after
  editing installer.nsh, the same way docs_check_mutations.py is run by hand.

.EXAMPLE
  pwsh -File build/check-installer-nsh.ps1
#>
[CmdletBinding()]
param(
  # Root of the electron-builder tool cache holding the downloaded NSIS.
  [string] $NsisCacheRoot = (Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\nsis')
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$nsh = Join-Path $repoRoot 'build\installer.nsh'
if (-not (Test-Path -LiteralPath $nsh)) {
  Write-Host "FAILED:installer-nsh missing $nsh"
  exit 1
}

$makensis = Get-ChildItem -LiteralPath $NsisCacheRoot -Recurse -Filter 'makensis.exe' -ErrorAction SilentlyContinue |
  Where-Object { $_.DirectoryName -notmatch '\\Bin$' } |
  Select-Object -First 1
if (-not $makensis) {
  # Absence of the tool is NOT a pass. Say so and exit non-zero so a caller can never
  # read "no output" as "verified".
  Write-Host "FAILED:installer-nsh makensis.exe not found under $NsisCacheRoot (run a Windows build once to populate the cache)"
  exit 1
}

# TWO PASSES, and /WX. Both additions come from a REAL escape (2026-08-08).
#
# v1 of this check modelled only the INSTALLER pass and compiled with /V2 but not /WX. It
# reported SUCCESS on an installer.nsh that electron-builder could not package at all:
#
#     warning 6001: Variable "ReframeProfile" not referenced or never set, wasting memory!
#     Error: warning treated as error
#
# Root cause: electron-builder runs makensis TWICE over the same script -- once for the
# installer, once for the UNINSTALLER with -DBUILD_UNINSTALLER (app-builder-lib
# templates/nsis/installer.nsi:90,:95 gate the whole install half on !ifndef BUILD_UNINSTALLER).
# In that second pass neither custom macro is inserted, so every Var declared at top level and
# used only inside those macros is declared-and-never-referenced -> 6001 -> /WX -> no installer.
#
# v1 was structurally blind to it: it ALWAYS inserted both macros, so it only ever exercised the
# state that works. That is a probe that is silent in the broken state -- it measured nothing.
# Both passes now run, and both use /WX exactly as electron-builder does.

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("reframe-nsh-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  Copy-Item -LiteralPath $nsh -Destination (Join-Path $work 'installer.nsh')

  # $InsertMacros mirrors whether app-builder-lib expands the custom macros in this pass.
  # `Page custom` needs a page slot, so MUI_PAGE_DIRECTORY stands in for the directory page
  # customPageAfterChangeDir is inserted after.
  function Build-Harness([bool]$InsertMacros) {
    $h = @(
      '!include MUI2.nsh'
      '!include LogicLib.nsh'
      '!include nsDialogs.nsh'
      ''
      'Name "Reframe"'
      'OutFile "harness.exe"'
      'InstallDir "$LOCALAPPDATA\Programs\Reframe"'
      'RequestExecutionLevel user'
      ''
      '!include "installer.nsh"'
      ''
      '!insertmacro MUI_PAGE_DIRECTORY'
    )
    if ($InsertMacros) {
      # app-builder-lib inserts this exact macro here (assistedInstaller.nsh:42).
      $h += '!ifmacrodef customPageAfterChangeDir'
      $h += '  !insertmacro customPageAfterChangeDir'
      $h += '!endif'
    }
    $h += '!insertmacro MUI_PAGE_INSTFILES'
    $h += '!insertmacro MUI_LANGUAGE "English"'
    $h += ''
    $h += 'Section "install"'
    if ($InsertMacros) {
      # app-builder-lib inserts this exact macro here (installSection.nsh:81).
      $h += '  !ifmacrodef customInstall'
      $h += '    !insertmacro customInstall'
      $h += '  !endif'
    }
    $h += 'SectionEnd'
    return ($h -join "`r`n")
  }

  function Invoke-Pass([string]$Label, [bool]$InsertMacros, [string[]]$ExtraArgs) {
    Set-Content -LiteralPath (Join-Path $work 'harness.nsi') -Value (Build-Harness $InsertMacros) -Encoding UTF8
    Push-Location $work
    try {
      # /WX is what electron-builder uses. Without it this check cannot see warning 6001.
      $passOut = & $makensis.FullName '/WX' '/V2' @ExtraArgs 'harness.nsi' 2>&1
      $passCode = $LASTEXITCODE
    } finally {
      Pop-Location
    }
    $passOut | ForEach-Object { Write-Host $_ }
    if ($passCode -ne 0) {
      Write-Host "FAILED:installer-nsh $Label pass -- makensis exit $passCode"
      return $passCode
    }
    Write-Host "  ok: $Label pass"
    return 0
  }

  # Pass 1 -- the installer. Macros inserted, as assistedInstaller.nsh/installSection.nsh do.
  $rc = Invoke-Pass 'installer' $true @()
  if ($rc -ne 0) { exit $rc }

  # Pass 2 -- the uninstaller. -DBUILD_UNINSTALLER and NO custom macros, which is what
  # app-builder-lib actually compiles. This is the pass that caught the 6001 escape.
  $rc = Invoke-Pass 'uninstaller' $false @('/DBUILD_UNINSTALLER')
  if ($rc -ne 0) { exit $rc }

  Write-Host "SUCCESS:installer-nsh both passes compiled with $($makensis.FullName)"
  exit 0
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
