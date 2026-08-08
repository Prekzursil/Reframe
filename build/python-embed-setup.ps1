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
#   build/ffmpeg/win/        ffmpeg.exe + ffprobe.exe + LICENSE   (BtbN win64-GPL,
#                            with -WithFfmpeg; shipped to resources/bin/). GPL, not
#                            LGPL: the LGPL build is --disable-libx264, which cannot
#                            encode the H.264 the whole app asks for. See the
#                            $FfmpegUrl block below for the full licence reasoning.
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
    # RECORDED 2026-07-26. python.org publishes MD5 (NOT SHA-256) on the release
    # page, so the two-signal check is: fetch over TLS, confirm the bytes against
    # the vendor's published MD5 for THIS EXACT row, then pin the SHA-256 of those
    # verified bytes. Vendor MD5 fe8ef205f2e9c3ba44d0cf9954e1abd3 (matched).
    # PARSE WARNING: the release-page MD5 column follows the filename inside the
    # same <tr>. Scanning BACKWARDS from the filename yields the PREVIOUS row's
    # digest (arm64.exe) and a false "supply chain mismatch" — scope to the row.
    [string]$ExpectedPythonSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3',
    # The dedicated py3.14 embed for the isolated chatterbox env (A4).
    [string]$ChatterboxPythonVersion = '3.14.0',  # human pins the exact patch on first verified run
    [string]$ChatterboxDest = (Join-Path $PSScriptRoot 'python-embed-314'),
    # REQUIRED (WU-S10) — same as above, for the py3.14 embed zip.
    # RECORDED 2026-07-26, same two-signal method. Vendor MD5
    # 7c5d8d8e3213a11bd0e36f8b8eb03431 (matched). NOTE: this URL 404'd as recently
    # as 2026-07-18 (3.14.0 was not yet published), which is why an earlier CI run
    # failed here for a DIFFERENT reason than the empty pin. It is live now.
    [string]$ExpectedChatterboxPythonSha256 = '8d4d3590c10449d78aa4375f534e6d5f3027d67fdc362dd1a882279db6f90fdf',
    [switch]$WithFfmpeg,
    # Pinned ffmpeg build (WU A3): BtbN win64-**GPL** STATIC. FFmpeg n7.1.5 line.
    #
    # *** WHY GPL, NOT LGPL (corrected 2026-08-08 — the previous rationale shipped a
    # BROKEN product). *** This pin used to read win64-**lgpl** with the argument that
    # "an UNMODIFIED LGPL exe invoked as a separate child process is redistribution-safe
    # in a closed-source app". The licence half of that sentence was fine; the
    # FUNCTIONAL half was never checked. BtbN's LGPL build is configured
    # `--disable-libx264 --disable-libx265` (read it off the shipped binary:
    # `ffmpeg -version` prints the full `configuration:` line), so it CANNOT encode
    # H.264 in software — while nine sidecar modules and the renderer default pass
    # `-c:v libx264` as a literal argv element. Measured on the installed 1.5 build:
    #   -c:v libx264     -> "Unknown encoder 'libx264'", exit 1, NO output file
    #   -c:v libopenh264 -> output produced
    # Every gate missed it because CI installs ffmpeg from apt/choco (a GPL build that
    # HAS libx264) and the packaged e2e never exercised an export.
    #
    # The GPL analysis that replaces it: FFmpeg is LGPL-2.1+ by default and
    # `--enable-gpl` (required for libx264/libx265) makes the resulting BINARY GPL-2+.
    # Reframe does not link it — `media_studio/ffmpeg.py::resolve_binary` resolves an
    # absolute path and `run()` spawns it as a SEPARATE CHILD PROCESS over an argv list
    # (never a library call, never `shell=True`). That is aggregation, not a derived
    # work, so shipping the unmodified GPL `ffmpeg.exe` does NOT relicense Reframe's own
    # source. What it DOES oblige is a written offer of the CORRESPONDING SOURCE for the
    # binary we redistribute: the exact upstream tag + asset + source URL are recorded
    # here, in electron-builder.yml, and user-facing in the app's Settings -> Licenses
    # surface (app/renderer/src/features/ThirdPartyNotices.tsx, FFMPEG_NOTICE).
    #
    # Deliberately a ONE-DIMENSION change: same BtbN release tag, same ffmpeg commit
    # (g7d0e842004), same n7.1.5 line, same asset shape — only `-lgpl-` becomes `-gpl-`,
    # so nothing but the licence/encoder set moves. The extractor below still copies the
    # zip's LICENSE.txt next to the exes (now the GPL text, which is the stronger
    # obligation: ship the licence + record this exact source tag).
    #
    # *** PIN A MONTH-END TAG ONLY. *** BtbN's retention is TWO-TIER, and getting
    # this wrong silently breaks the Windows build weeks later:
    #   - the last ~2 weeks of DAILY autobuilds are kept, then deleted;
    #   - only the LAST-DAY-OF-MONTH build is retained long-term (~2 years:
    #     2026-06-30, 2026-05-31, ... back to 2024-08-31 as of 2026-07-26).
    # The previous pin, autobuild-2026-07-03-13-21, was a MID-MONTH DAILY. It was
    # pruned and began returning 404, which failed `Stage packaged runtime` on
    # every Windows CI run. Re-pinned 2026-07-26 to the 2026-06-30 month-end tag,
    # which carries the SAME asset (identical filename + ffmpeg commit
    # g7d0e842004) and is retained for years rather than days.
    [string]$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-06-30-13-34/ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip',
    # REQUIRED (WU-S10) when -WithFfmpeg is used: empty => the download is
    # REFUSED. BtbN publishes no per-asset checksum file, so this is the digest of
    # the exact pinned asset. RE-RECORDED 2026-08-08 for the win64-GPL asset
    # (verified to contain bin/ffmpeg.exe, bin/ffprobe.exe and LICENSE.txt, and to
    # report `--enable-gpl --enable-libx264 --enable-libx265` in its own
    # `ffmpeg -version` configuration line). The superseded LGPL digest was
    # ec1c6ae03fab10f316344973f83c549b4b662ec3d73f1658353ab1587f4cf727 — recorded
    # here so a future reader can tell the two assets apart rather than assuming
    # the pin merely rotated.
    [string]$ExpectedFfmpegSha256 = '405b190f746db40539eb453967f72c0e69d8bf260b10ceff36e0c2149a9ad22f',
    [string]$FfmpegDest = (Join-Path (Join-Path $PSScriptRoot 'ffmpeg') 'win'),
    [string]$GetPipUrl = 'https://bootstrap.pypa.io/get-pip.py',
    # get-pip.py is DOWNLOADED then EXECUTED, so it is the most important pin
    # here. This is the SAME digest the runtime already enforces —
    # sidecar/media_studio/assets/manager.py::GET_PIP_SHA256 (pinned 2026-06-28,
    # 2,226,848 B), which sidecar/runtime_setup/bootstrap.py imports. Keep the
    # three in sync when pypa rotates get-pip.
    # ROTATED 2026-07-30 alongside the runtime constant. pypa republished the rolling URL
    # (Last-Modified "Wed, 29 Jul 2026 22:35:44 GMT"), so the previous digest
    # a341e1a4...7055 (2,226,848 B) started failing closed. Current: 2,230,427 B, pip 26.2.
    # Provenance + its limits are documented at the runtime site, which is the SSOT —
    # see sidecar/media_studio/assets/manager.py::GET_PIP_SHA256. Keep the two in lockstep.
    [string]$ExpectedGetPipSha256 = 'fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6',
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
