# python-embed-setup.ps1 — stage the packaged runtime resources (PLAN-P2 T5).
#
# *** NETWORK SCRIPT — run MANUALLY at build prep, never from an agent session ***
#
# Stages the extraResources inputs electron-builder.yml expects:
#   build/python-embed/      embeddable CPython 3.12 (+ a staged get-pip.py so the
#                            first-run bootstrap works offline-after-install)
#   build/python-embed-314/  embeddable CPython 3.14 (+ get-pip.py) — the DEDICATED
#                            interpreter for the ISOLATED chatterbox voice-clone env
#                            (torch 2.10 only resolves on py3.14; CONTRACTS.md A4)
#   build/ffmpeg/win/        ffmpeg.exe + ffprobe.exe + LICENSE   (BtbN win64-LGPL,
#                            with -WithFfmpeg; shipped to resources/bin/)
#
# Everything downloaded is PINNED by exact URL (A6 lesson 5). SHA-256 of each
# download is printed (and optionally enforced) so the pins can be hardened:
# run once, copy the printed hash into the -Expected*Sha256 parameter defaults.
#
# CONTRACT-NOTE: 3.12.10 is the FINAL 3.12 release that ships Windows binaries
# (the branch is security-only afterwards) — the highest pinnable embed zip.
# The chatterbox env needs py3.14 because chatterbox-tts 0.1.7 only accepts
# torch>=2.9.0 (we pin 2.10.0) on python_version>="3.14"; py3.14 also ships a
# Windows embed-amd64.zip (same URL shape as 3.12). The chatterbox embed's
# python314._pth is left AS SHIPPED: that env is consumed purely via
# PYTHONPATH/--target (never ._pth activation — it is not the sidecar runtime).

[CmdletBinding()]
param(
    [string]$PythonVersion = '3.12.10',
    [string]$Dest = (Join-Path $PSScriptRoot 'python-embed'),
    [string]$ExpectedPythonSha256 = '',   # fill in after the first verified run
    # The dedicated py3.14 embed for the isolated chatterbox env (A4).
    [string]$ChatterboxPythonVersion = '3.14.0',  # human pins the exact patch on first verified run
    [string]$ChatterboxDest = (Join-Path $PSScriptRoot 'python-embed-314'),
    [string]$ExpectedChatterboxPythonSha256 = '',  # fill in after the first verified run
    [switch]$WithFfmpeg,
    # Pinned ffmpeg build (WU A3): BtbN win64-LGPL STATIC (~138 MB zip). BtbN is
    # the only mainstream source with a redistribution-safe LGPL static Windows
    # build (gyan.dev main builds are all --enable-gpl); an UNMODIFIED LGPL exe
    # invoked as a separate child process is redistribution-safe in a closed-
    # source app. PINNED release tag: autobuild-2026-07-03-13-21 (durable dated
    # asset, not the rolling `latest` tag), FFmpeg n7.1.5 line. The extractor
    # below also copies the zip's LICENSE.txt next to the exes (LGPL obligation:
    # ship the license + record this exact source tag). Fill the sha256 on the
    # first verified offline download.
    [string]$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-03-13-21/ffmpeg-n7.1.5-1-g7d0e842004-win64-lgpl-7.1.zip',
    [string]$ExpectedFfmpegSha256 = '',
    [string]$FfmpegDest = (Join-Path (Join-Path $PSScriptRoot 'ffmpeg') 'win'),
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

    # -- dedicated embeddable CPython 3.14 (chatterbox env, A4) -----------------
    if ((Test-Path (Join-Path $ChatterboxDest 'python.exe')) -and -not $Force) {
        Write-Host "[embed-setup] $ChatterboxDest already staged (use -Force to redo)"
    } else {
        $cbUrl = "https://www.python.org/ftp/python/$ChatterboxPythonVersion/python-$ChatterboxPythonVersion-embed-amd64.zip"
        $cbZip = Join-Path ([IO.Path]::GetTempPath()) "python-$ChatterboxPythonVersion-embed-amd64.zip"
        Get-Download -Url $cbUrl -OutFile $cbZip -ExpectedSha256 $ExpectedChatterboxPythonSha256
        if (Test-Path $ChatterboxDest) { Remove-Item $ChatterboxDest -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $ChatterboxDest | Out-Null
        Expand-Archive -Path $cbZip -DestinationPath $ChatterboxDest -Force
        Remove-Item $cbZip -Force
        if (-not (Test-Path (Join-Path $ChatterboxDest 'python.exe'))) {
            throw "chatterbox embed zip extracted but python.exe is missing in $ChatterboxDest"
        }
        # NOTE: python314._pth left AS SHIPPED — the chatterbox env is consumed via
        # PYTHONPATH/--target only (never ._pth activation; it is not the runtime).
    }

    # -- staged get-pip.py beside the py3.14 embed (no ensurepip there either) --
    $cbGetPip = Join-Path $ChatterboxDest 'get-pip.py'
    if ((Test-Path $cbGetPip) -and -not $Force) {
        Write-Host "[embed-setup] chatterbox get-pip.py already staged"
    } else {
        Get-Download -Url $GetPipUrl -OutFile $cbGetPip -ExpectedSha256 ''
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
                # Preserve an existing extension (BtbN ships LICENSE.txt / README.txt);
                # only append .txt when the source name is extensionless, so the doc
                # lands as a single LICENSE.txt (not the old LICENSE.txt.txt).
                $docName = if ([IO.Path]::GetExtension($doc.Name)) { $doc.Name } else { $doc.Name + '.txt' }
                Copy-Item $doc.FullName (Join-Path $FfmpegDest $docName) -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $tmpZip -Force
            Remove-Item $tmpDir -Recurse -Force
        }
    }

    Write-Host "SUCCESS:python-embed-setup staged python-embed + python-embed-314$(if ($WithFfmpeg) { ' + ffmpeg' })"
    exit 0
} catch {
    Write-Host "FAILED:python-embed-setup $($_.Exception.Message)"
    exit 1
}
