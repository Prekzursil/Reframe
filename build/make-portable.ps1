# make-portable.ps1 — produce + validate the portable zip (PLAN-P2 T5).
#
# Runs AFTER electron-builder (see electron-builder.yml header for the order).
# Zips dist/win-unpacked into a portable artifact and enforces the SLIM rules:
#   * no torch, no model weights (*.gguf/*.onnx/*.safetensors/*.pt), no envs —
#    heavy bits belong to FIRST RUN (%APPDATA%/media-studio), never the artifact
#   * total size sanity vs the < ~700 MB target (NSIS ~2 GB ceiling far behind)
#
# Offline; touches only dist/. Output is terminal-state: SUCCESS:/FAILED:.

[CmdletBinding()]
param(
    [string]$UnpackedDir = (Join-Path $PSScriptRoot '..\dist\win-unpacked'),
    [string]$OutZip = (Join-Path $PSScriptRoot '..\dist\media-studio-portable-win-x64.zip'),
    [int]$MaxMB = 700,
    [switch]$SkipZip   # only run the slim checks (CI gate mode)
)

$ErrorActionPreference = 'Stop'

try {
    if (-not (Test-Path (Join-Path $UnpackedDir 'resources'))) {
        throw "unpacked build not found at $UnpackedDir - run electron-builder first (see electron-builder.yml header)"
    }

    # -- slim assertions ---------------------------------------------------------
    $violations = @()

    $weightPatterns = '*.gguf', '*.safetensors', '*.pt', '*.ckpt'
    $weights = Get-ChildItem -Path $UnpackedDir -Recurse -Include $weightPatterns -ErrorAction SilentlyContinue
    if ($weights) {
        $violations += "model weights inside the artifact: $(($weights | Select-Object -First 5 | ForEach-Object Name) -join ', ')"
    }

    # torch must never ship (A6 lesson 5 / section 7) - look for a torch package dir
    $torch = Get-ChildItem -Path $UnpackedDir -Recurse -Directory -Filter 'torch' -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'version.py') }
    if ($torch) { $violations += "a torch package is inside the artifact: $($torch[0].FullName)" }

    # heavy first-run envs must not be pre-baked into resources
    $envsDir = Join-Path $UnpackedDir 'resources\sidecar\envs'
    if (Test-Path $envsDir) { $violations += "resources/sidecar/envs must not ship (first-run installs envs)" }

    # the staged runtime must be present (two-stage contract: stage 1 carries these)
    foreach ($required in 'resources\python\python.exe', 'resources\bin\ffmpeg.exe',
                          'resources\sidecar\media_studio\__main__.py',
                          'resources\sidecar\runtime_setup\bootstrap.py',
                          'resources\render-cli\dist\render.js',
                          'resources\render-cli\out\remotion-bundle') {
        if (-not (Test-Path (Join-Path $UnpackedDir $required))) {
            $violations += "missing staged resource: $required"
        }
    }

    $sizeBytes = (Get-ChildItem -Path $UnpackedDir -Recurse -File | Measure-Object -Sum Length).Sum
    $sizeMB = [math]::Round($sizeBytes / 1MB)
    Write-Host "[make-portable] unpacked size: $sizeMB MB (target < $MaxMB MB)"
    if ($sizeMB -gt $MaxMB) {
        $violations += "unpacked build is $sizeMB MB (> $MaxMB MB slim target)"
    }

    if ($violations.Count -gt 0) {
        foreach ($v in $violations) { Write-Host "FAILED:make-portable $v" }
        exit 1
    }

    # -- zip -----------------------------------------------------------------------
    if (-not $SkipZip) {
        if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
        Write-Host "[make-portable] compressing $UnpackedDir -> $OutZip"
        Compress-Archive -Path (Join-Path $UnpackedDir '*') -DestinationPath $OutZip -CompressionLevel Optimal
        $zipMB = [math]::Round((Get-Item $OutZip).Length / 1MB)
        Write-Host "[make-portable] zip size: $zipMB MB"
    }

    Write-Host "SUCCESS:make-portable slim checks passed$(if (-not $SkipZip) { ', zip written' })"
    exit 0
} catch {
    Write-Host "FAILED:make-portable $($_.Exception.Message)"
    exit 1
}
