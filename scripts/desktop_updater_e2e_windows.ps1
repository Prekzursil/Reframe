param(
  [string]$OldTag = "desktop-v0.1.6",
  [string]$NewTag = "desktop-v0.1.7",
  [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"

function Get-VersionFromTag {
  param([string]$Tag)
  if ($Tag.StartsWith("desktop-v")) { return $Tag.Substring("desktop-v".Length) }
  if ($Tag.StartsWith("v")) { return $Tag.Substring(1) }
  return $Tag
}

function Get-ReframeInstallEntry {
  $paths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )

  foreach ($path in $paths) {
    $items = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -like "Reframe*" } |
      Sort-Object DisplayVersion -Descending
    if ($items) {
      return $items[0]
    }
  }
  return $null
}

function Uninstall-ReframeIfPresent {
  $entry = Get-ReframeInstallEntry
  if ($null -eq $entry) { return $null }

  $productCode = $null
  if ($entry.PSChildName -match "^\{[0-9A-Fa-f\-]+\}$") {
    $productCode = $entry.PSChildName
  }

  if (-not $productCode -and $entry.UninstallString) {
    $m = [regex]::Match($entry.UninstallString, "\{[0-9A-Fa-f\-]+\}")
    if ($m.Success) {
      $productCode = $m.Value
    }
  }

  if ($productCode) {
    Start-Process msiexec.exe -ArgumentList @("/x", $productCode, "/qn", "/norestart") -Wait -NoNewWindow | Out-Null
  } elseif ($entry.UninstallString) {
    $args = $entry.UninstallString -replace "(?i)/I", "/X"
    Start-Process "cmd.exe" -ArgumentList @("/c", "$args /qn /norestart") -Wait -NoNewWindow | Out-Null
  }

  return $entry.DisplayVersion
}

function Install-Msi {
  param([string]$Path)
  Start-Process msiexec.exe -ArgumentList @("/i", $Path, "/qn", "/norestart") -Wait -NoNewWindow | Out-Null
}

try {
  if (-not $WorkDir) {
    $WorkDir = Join-Path $env:TEMP "reframe-updater-e2e"
  }
  New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

  $oldVersion = Get-VersionFromTag -Tag $OldTag
  $newVersion = Get-VersionFromTag -Tag $NewTag
  $oldAsset = "Reframe_${oldVersion}_x64_en-US.msi"
  $newAsset = "Reframe_${newVersion}_x64_en-US.msi"

  if (-not $env:GH_TOKEN -and $env:GITHUB_TOKEN) {
    $env:GH_TOKEN = $env:GITHUB_TOKEN
  }

  & gh release download $OldTag -R Prekzursil/Reframe -p $oldAsset -D $WorkDir --clobber | Out-Null
  & gh release download $NewTag -R Prekzursil/Reframe -p $newAsset -D $WorkDir --clobber | Out-Null

  $oldPath = Join-Path $WorkDir $oldAsset
  $newPath = Join-Path $WorkDir $newAsset

  $uninstalled = Uninstall-ReframeIfPresent

  Install-Msi -Path $oldPath
  $afterOld = Get-ReframeInstallEntry
  if ($null -eq $afterOld) {
    throw "Old installer did not produce an installed Reframe entry."
  }

  Install-Msi -Path $newPath
  $afterNew = Get-ReframeInstallEntry
  if ($null -eq $afterNew) {
    throw "New installer did not produce an installed Reframe entry."
  }

  $result = [ordered]@{
    platform = "windows"
    success = $true
    old_tag = $OldTag
    new_tag = $NewTag
    expected_old_version = $oldVersion
    expected_new_version = $newVersion
    observed_old_version = [string]$afterOld.DisplayVersion
    observed_new_version = [string]$afterNew.DisplayVersion
    uninstalled_previous_version = $uninstalled
    old_asset = $oldAsset
    new_asset = $newAsset
    work_dir = $WorkDir
  }

  $result | ConvertTo-Json -Depth 8
}
catch {
  $failure = [ordered]@{
    platform = "windows"
    success = $false
    error = $_.Exception.Message
    old_tag = $OldTag
    new_tag = $NewTag
  }
  $failure | ConvertTo-Json -Depth 8
  exit 1
}
