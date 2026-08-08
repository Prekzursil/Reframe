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

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("reframe-nsh-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  # The harness mirrors app-builder-lib's own structure closely enough to expand both
  # macros in a realistic context, and no further. `Page custom` needs a page slot, so
  # MUI_PAGE_DIRECTORY stands in for the directory page it is inserted after.
  $harness = @'
!include MUI2.nsh
!include LogicLib.nsh
!include nsDialogs.nsh

Name "Reframe"
OutFile "harness.exe"
InstallDir "$LOCALAPPDATA\Programs\Reframe"
RequestExecutionLevel user

!include "installer.nsh"

!insertmacro MUI_PAGE_DIRECTORY
; app-builder-lib inserts this exact macro here (assistedInstaller.nsh:42).
!ifmacrodef customPageAfterChangeDir
  !insertmacro customPageAfterChangeDir
!endif
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "install"
  ; app-builder-lib inserts this exact macro here (installSection.nsh:81).
  !ifmacrodef customInstall
    !insertmacro customInstall
  !endif
SectionEnd
'@
  Set-Content -LiteralPath (Join-Path $work 'harness.nsi') -Value $harness -Encoding UTF8
  Copy-Item -LiteralPath $nsh -Destination (Join-Path $work 'installer.nsh')

  Push-Location $work
  try {
    $out = & $makensis.FullName '/V2' 'harness.nsi' 2>&1
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
  }

  $out | ForEach-Object { Write-Host $_ }
  if ($code -ne 0) {
    Write-Host "FAILED:installer-nsh makensis exit $code"
    exit $code
  }
  Write-Host "SUCCESS:installer-nsh compiled with $($makensis.FullName)"
  exit 0
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
