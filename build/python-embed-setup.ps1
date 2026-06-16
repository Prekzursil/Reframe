# python-embed-setup.ps1 — stage the packaged runtime resources (PLAN-P2 T5).
#
# *** NETWORK SCRIPT — run MANUALLY at build prep, never from an agent session ***
#
# Stages the extraResources inputs electron-builder.yml expects:
#   build/python-embed/   embeddable CPython 3.12 (+ a staged get-pip.py so the
#                         first-run bootstrap works offline-after-install)
#   build/ffmpeg/         ffmpeg.exe + ffprobe.exe   (with -WithFfmpeg)
#
# Everything downloaded is PINNED by exact URL (A6 lesson 5). SHA-256 of each
# download is printed (and optionally enforced) so the pins can be hardened:
# run once, copy the printed hash into the -Expected*Sha256 parameter defaults.
#
# CONTRACT-NOTE: 3.12.10 is the FINAL 3.12 release that ships Windows binaries
# (the branch is security-only afterwards) — the highest pinnable embed zip.

[CmdletBinding()]
param(
    [string]$PythonVersion = '3.12.10',
    [string]$Dest = (Join-Path $PSScriptRoot 'python-embed'),
    [string]$ExpectedPythonSha256 = '',   # fill in after the first verified run
    [switch]$WithFfmpeg,
    # Pinned ffmpeg build (gyan.dev essentials; ~80 MB zip). Verify on first run.
    [string]$FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-7.1.1-essentials_build.zip',
    [string]$ExpectedFfmpegSha256 = '',
    [string]$FfmpegDest = (Join-Path $PSScriptRoot 'ffmpeg'),
    [string]$GetPipUrl = 'https://bootstrap.pypa.io/get-pip.py',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-Download {
    param([string]$Url, [string]$OutFile, [string]$ExpectedSha256)
    Write-Host "[embed-setup] downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
    $hash = (Get-FileHash -Algorithm SHA256 -Path $OutFile).Hash.ToLowerInvariant()
    Write-Host "[embed-setup] sha256($([IO.Path]::GetFileName($OutFile))) = $hash"
    if ($ExpectedSha256 -and ($hash -ne $ExpectedSha256.ToLowerInvariant())) {
        Remove-Item $OutFile -Force
        throw "sha256 mismatch for $Url (expected $ExpectedSha256, got $hash)"
    }
}

try {
    # -- embeddable CPython ----------------------------------------------------
    if ((Test-Path (Join-Path $Dest 'python.exe')) -and -not $Force) {
        Write-Host "[embed-setup] $Dest already staged (use -Force to redo)"
    } else {
        $pyUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
        $tmpZip = Join-Path ([IO.Path]::GetTempPath()) "python-$PythonVersion-embed-amd64.zip"
        Get-Download -Url $pyUrl -OutFile $tmpZip -ExpectedSha256 $ExpectedPythonSha256
        if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        Expand-Archive -Path $tmpZip -DestinationPath $Dest -Force
        Remove-Item $tmpZip -Force
        if (-not (Test-Path (Join-Path $Dest 'python.exe'))) {
            throw "embed zip extracted but python.exe is missing in $Dest"
        }
        # NOTE: the default python312._pth is left AS SHIPPED here. The first-run
        # bootstrap (runtime_setup/bootstrap.py) rewrites it on the TARGET machine
        # with the %APPDATA% env activation (write_pth) — paths are per-machine.
    }

    # -- staged get-pip.py (lets first run work without bootstrap.pypa.io) ------
    $getPip = Join-Path $Dest 'get-pip.py'
    if ((Test-Path $getPip) -and -not $Force) {
        Write-Host "[embed-setup] get-pip.py already staged"
    } else {
        Get-Download -Url $GetPipUrl -OutFile $getPip -ExpectedSha256 ''
    }

    # -- ffmpeg/ffprobe ----------------------------------------------------------
    if ($WithFfmpeg) {
        if ((Test-Path (Join-Path $FfmpegDest 'ffmpeg.exe')) -and -not $Force) {
            Write-Host "[embed-setup] $FfmpegDest already staged"
        } else {
            $tmpZip = Join-Path ([IO.Path]::GetTempPath()) 'ffmpeg-pinned.zip'
            $tmpDir = Join-Path ([IO.Path]::GetTempPath()) 'ffmpeg-pinned-extract'
            Get-Download -Url $FfmpegUrl -OutFile $tmpZip -ExpectedSha256 $ExpectedFfmpegSha256
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
            Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
            New-Item -ItemType Directory -Force -Path $FfmpegDest | Out-Null
            foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
                $found = Get-ChildItem -Path $tmpDir -Recurse -Filter $exe | Select-Object -First 1
                if (-not $found) { throw "$exe not found inside $FfmpegUrl" }
                Copy-Item $found.FullName (Join-Path $FfmpegDest $exe) -Force
            }
            $license = Get-ChildItem -Path $tmpDir -Recurse -Include 'LICENSE*', 'README*' |
                Select-Object -First 2
            foreach ($doc in $license) {
                Copy-Item $doc.FullName (Join-Path $FfmpegDest ($doc.Name + '.txt')) -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $tmpZip -Force
            Remove-Item $tmpDir -Recurse -Force
        }
    }

    Write-Host "SUCCESS:python-embed-setup staged python-embed$(if ($WithFfmpeg) { ' + ffmpeg' })"
    exit 0
} catch {
    Write-Host "FAILED:python-embed-setup $($_.Exception.Message)"
    exit 1
}
