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
# Everything downloaded is PINNED by exact URL (A6 lesson 5) *and* by SHA-256.
#
# WU-S10 (T4 supply chain) — the SHA-256 pin is MANDATORY and FAILS CLOSED.
# Previously the -Expected*Sha256 parameters defaulted to '' and were only
# checked `if ($ExpectedSha256 -and ...)`, so verification was OPTIONAL: a
# swapped/MITM'd upstream asset (CPython, get-pip, ffmpeg) was extracted and
# PACKAGED silently. Now an empty or malformed pin REFUSES the download before a
# single request is made, and nothing is ever staged from unverified bytes.
#
# To learn a hash for a NEW pin (the chicken-and-egg bootstrap), run with
# -RecordHashes: it fetches each artifact, prints its sha256, DELETES it, stages
# NOTHING and exits non-zero. Paste the printed values into the matching
# -Expected*Sha256 defaults below (cross-check them against the vendor's own
# published checksums), then re-run WITHOUT -RecordHashes to actually stage.
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
    # REQUIRED (WU-S10): empty => the download is REFUSED, nothing is staged.
    # Obtain with -RecordHashes and cross-check against python.org's published
    # SHA-256 for python-<ver>-embed-amd64.zip before recording it here.
    [string]$ExpectedPythonSha256 = '',
    # The dedicated py3.14 embed for the isolated chatterbox env (A4).
    [string]$ChatterboxPythonVersion = '3.14.0',  # human pins the exact patch on first verified run
    [string]$ChatterboxDest = (Join-Path $PSScriptRoot 'python-embed-314'),
    # REQUIRED (WU-S10) — same as above, for the py3.14 embed zip.
    [string]$ExpectedChatterboxPythonSha256 = '',
    [switch]$WithFfmpeg,
    # Pinned ffmpeg build (WU A3): BtbN win64-LGPL STATIC (~138 MB zip). BtbN is
    # the only mainstream source with a redistribution-safe LGPL static Windows
    # build (gyan.dev main builds are all --enable-gpl); an UNMODIFIED LGPL exe
    # invoked as a separate child process is redistribution-safe in a closed-
    # source app. PINNED release tag: autobuild-2026-07-03-13-21 (durable dated
    # asset, not the rolling `latest` tag), FFmpeg n7.1.5 line. The extractor
    # below also copies the zip's LICENSE.txt next to the exes (LGPL obligation:
    # ship the license + record this exact source tag).
    [string]$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-03-13-21/ffmpeg-n7.1.5-1-g7d0e842004-win64-lgpl-7.1.zip',
    # REQUIRED (WU-S10) when -WithFfmpeg is used: empty => the download is
    # REFUSED. BtbN publishes no per-asset checksum file, so obtain it with
    # -RecordHashes and record the digest of the exact pinned release asset.
    [string]$ExpectedFfmpegSha256 = '',
    [string]$FfmpegDest = (Join-Path (Join-Path $PSScriptRoot 'ffmpeg') 'win'),
    [string]$GetPipUrl = 'https://bootstrap.pypa.io/get-pip.py',
    # get-pip.py is DOWNLOADED then EXECUTED, so it is the most important pin
    # here. This is the SAME digest the runtime already enforces —
    # sidecar/media_studio/assets/manager.py::GET_PIP_SHA256 (pinned 2026-06-28,
    # 2,226,848 B), which sidecar/runtime_setup/bootstrap.py imports. Keep the
    # three in sync when pypa rotates get-pip.
    [string]$ExpectedGetPipSha256 = 'a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055',
    # Fail-closed bootstrap escape hatch: fetch every artifact, PRINT its sha256,
    # delete it, stage NOTHING, exit non-zero. The only way to obtain a pin you
    # do not have yet — it can never produce a build.
    [switch]$RecordHashes,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# The embeddable-CPython download URL for a version (same shape for 3.12/3.14).
function Get-EmbedUrl {
    param([string]$Version)
    return "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
}

# Fetch to a .part file and return its sha256. NEVER leaves a partial behind: a
# transport failure deletes the .part and rethrows, so a truncated artifact can
# never be mistaken for a staged one on a later run (the old code wrote get-pip.py
# straight to its final staged path, so an interrupted fetch left a TRUNCATED
# get-pip.py that the next run reported as "already staged").
function Get-VerifiedPart {
    param([string]$Url, [string]$PartFile)
    Write-Host "[embed-setup] downloading $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $PartFile -UseBasicParsing
    } catch {
        if (Test-Path $PartFile) { Remove-Item $PartFile -Force }
        throw
    }
    return (Get-FileHash -Algorithm SHA256 -Path $PartFile).Hash.ToLowerInvariant()
}

# WU-S10: the pin gate. Runs BEFORE any network request, so a missing/malformed
# pin means the request is never made — not "download anyway and hope".
function Assert-Sha256Pin {
    param([string]$Url, [string]$ExpectedSha256, [string]$PinParameter)
    if (-not $ExpectedSha256) {
        throw ("refusing to download $Url : -$PinParameter is empty. A SHA-256 pin is MANDATORY " +
            '(WU-S10 fail-closed) so a swapped upstream asset cannot be packaged. ' +
            'Re-run with -RecordHashes to print the current digests, verify them against the ' +
            "vendor's published checksums, then set -$PinParameter and re-run.")
    }
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "-$PinParameter must be 64 hex chars (a SHA-256 digest), got '$ExpectedSha256'"
    }
}

function Get-Download {
    param([string]$Url, [string]$OutFile, [string]$ExpectedSha256, [string]$PinParameter)
    Assert-Sha256Pin -Url $Url -ExpectedSha256 $ExpectedSha256 -PinParameter $PinParameter
    $part = "$OutFile.part"
    $hash = Get-VerifiedPart -Url $Url -PartFile $part
    Write-Host "[embed-setup] sha256($([IO.Path]::GetFileName($OutFile))) = $hash"
    if ($hash -ne $ExpectedSha256.ToLowerInvariant()) {
        Remove-Item $part -Force
        throw "sha256 mismatch for $Url (expected $ExpectedSha256, got $hash)"
    }
    # Verified: only now does it become the staged artifact (atomic rename).
    Move-Item -LiteralPath $part -Destination $OutFile -Force
}

# -RecordHashes: print every artifact's digest, stage NOTHING, fail the run.
function Invoke-HashDiscovery {
    $probes = @(
        @{ Url = (Get-EmbedUrl $PythonVersion); Pin = 'ExpectedPythonSha256' }
        @{ Url = (Get-EmbedUrl $ChatterboxPythonVersion); Pin = 'ExpectedChatterboxPythonSha256' }
        @{ Url = $GetPipUrl; Pin = 'ExpectedGetPipSha256' }
    )
    if ($WithFfmpeg) { $probes += @{ Url = $FfmpegUrl; Pin = 'ExpectedFfmpegSha256' } }
    $tmpDir = Join-Path ([IO.Path]::GetTempPath()) "embed-setup-record-$PID"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    try {
        foreach ($probe in $probes) {
            $part = Join-Path $tmpDir ([IO.Path]::GetRandomFileName())
            $hash = Get-VerifiedPart -Url $probe.Url -PartFile $part
            Write-Host "[embed-setup] -$($probe.Pin) '$hash'"
            Remove-Item $part -Force
        }
    } finally {
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    # -- WU-S10 pin-discovery mode: never stages, always fails ----------------
    if ($RecordHashes) {
        Invoke-HashDiscovery
        Write-Host ('FAILED:python-embed-setup -RecordHashes staged NOTHING by design. ' +
            'Record the printed -Expected*Sha256 values (cross-check them against the ' +
            "vendor's published checksums), then re-run WITHOUT -RecordHashes.")
        exit 1
    }

    # -- embeddable CPython ----------------------------------------------------
    if ((Test-Path (Join-Path $Dest 'python.exe')) -and -not $Force) {
        Write-Host "[embed-setup] $Dest already staged (use -Force to redo)"
    } else {
        $pyUrl = Get-EmbedUrl $PythonVersion
        $tmpZip = Join-Path ([IO.Path]::GetTempPath()) "python-$PythonVersion-embed-amd64.zip"
        Get-Download -Url $pyUrl -OutFile $tmpZip -ExpectedSha256 $ExpectedPythonSha256 -PinParameter 'ExpectedPythonSha256'
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
        Get-Download -Url $GetPipUrl -OutFile $getPip -ExpectedSha256 $ExpectedGetPipSha256 -PinParameter 'ExpectedGetPipSha256'
    }

    # -- dedicated embeddable CPython 3.14 (chatterbox env, A4) -----------------
    if ((Test-Path (Join-Path $ChatterboxDest 'python.exe')) -and -not $Force) {
        Write-Host "[embed-setup] $ChatterboxDest already staged (use -Force to redo)"
    } else {
        $cbUrl = Get-EmbedUrl $ChatterboxPythonVersion
        $cbZip = Join-Path ([IO.Path]::GetTempPath()) "python-$ChatterboxPythonVersion-embed-amd64.zip"
        Get-Download -Url $cbUrl -OutFile $cbZip -ExpectedSha256 $ExpectedChatterboxPythonSha256 -PinParameter 'ExpectedChatterboxPythonSha256'
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
        Get-Download -Url $GetPipUrl -OutFile $cbGetPip -ExpectedSha256 $ExpectedGetPipSha256 -PinParameter 'ExpectedGetPipSha256'
    }

    # -- ffmpeg/ffprobe ----------------------------------------------------------
    if ($WithFfmpeg) {
        if ((Test-Path (Join-Path $FfmpegDest 'ffmpeg.exe')) -and -not $Force) {
            Write-Host "[embed-setup] $FfmpegDest already staged"
        } else {
            $tmpZip = Join-Path ([IO.Path]::GetTempPath()) 'ffmpeg-pinned.zip'
            $tmpDir = Join-Path ([IO.Path]::GetTempPath()) 'ffmpeg-pinned-extract'
            Get-Download -Url $FfmpegUrl -OutFile $tmpZip -ExpectedSha256 $ExpectedFfmpegSha256 -PinParameter 'ExpectedFfmpegSha256'
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
