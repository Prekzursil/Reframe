#!/usr/bin/env bash
set -euo pipefail

old_tag="desktop-v0.1.6"
new_tag="desktop-v0.1.7"
work_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --old-tag)
      old_tag="${2:-}"
      shift 2
      ;;
    --new-tag)
      new_tag="${2:-}"
      shift 2
      ;;
    --work-dir)
      work_dir="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

version_from_tag() {
  local tag="$1"
  if [[ "$tag" == desktop-v* ]]; then
    echo "${tag#desktop-v}"
  elif [[ "$tag" == v* ]]; then
    echo "${tag#v}"
  else
    echo "$tag"
  fi
}

plist_version() {
  local app_path="$1"
  /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app_path/Contents/Info.plist"
}

mount_dmg() {
  local dmg_path="$1"
  hdiutil attach "$dmg_path" -nobrowse -quiet | tail -n1 | awk '{print $3}'
}

if [[ -z "$work_dir" ]]; then
  work_dir="${TMPDIR:-/tmp}/reframe-updater-e2e"
fi
mkdir -p "$work_dir"

old_version="$(version_from_tag "$old_tag")"
new_version="$(version_from_tag "$new_tag")"

arch_raw="$(uname -m | tr '[:upper:]' '[:lower:]')"
if [[ "$arch_raw" == arm64 || "$arch_raw" == aarch64 ]]; then
  arch_suffix="aarch64"
else
  arch_suffix="x64"
fi

old_asset="Reframe_${old_version}_${arch_suffix}.dmg"
new_asset="Reframe_${new_version}_${arch_suffix}.dmg"

if [[ -z "${GH_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
  export GH_TOKEN="$GITHUB_TOKEN"
fi

gh release download "$old_tag" -R Prekzursil/Reframe -p "$old_asset" -D "$work_dir" --clobber >/dev/null
gh release download "$new_tag" -R Prekzursil/Reframe -p "$new_asset" -D "$work_dir" --clobber >/dev/null

old_dmg="$work_dir/$old_asset"
new_dmg="$work_dir/$new_asset"
install_root="$HOME/Applications"
install_app="$install_root/Reframe.app"
mkdir -p "$install_root"

rm -rf "$install_app"

old_mount="$(mount_dmg "$old_dmg")"
old_bundle="$(find "$old_mount" -maxdepth 2 -type d -name '*.app' | head -n1)"
if [[ -z "$old_bundle" ]]; then
  echo "Could not find .app bundle in old DMG" >&2
  exit 1
fi
cp -R "$old_bundle" "$install_app"
observed_old_version="$(plist_version "$install_app")"
hdiutil detach "$old_mount" -quiet || true

new_mount="$(mount_dmg "$new_dmg")"
new_bundle="$(find "$new_mount" -maxdepth 2 -type d -name '*.app' | head -n1)"
if [[ -z "$new_bundle" ]]; then
  echo "Could not find .app bundle in new DMG" >&2
  exit 1
fi
rm -rf "$install_app"
cp -R "$new_bundle" "$install_app"
observed_new_version="$(plist_version "$install_app")"
hdiutil detach "$new_mount" -quiet || true

python3 - <<'PY' "$old_tag" "$new_tag" "$old_version" "$new_version" "$observed_old_version" "$observed_new_version" "$old_asset" "$new_asset" "$work_dir"
from __future__ import annotations

import json
import sys

(
    old_tag,
    new_tag,
    old_version,
    new_version,
    observed_old,
    observed_new,
    old_asset,
    new_asset,
    work_dir,
) = sys.argv[1:]

payload = {
    "platform": "macos",
    "success": observed_old == old_version and observed_new == new_version,
    "old_tag": old_tag,
    "new_tag": new_tag,
    "expected_old_version": old_version,
    "expected_new_version": new_version,
    "observed_old_version": observed_old,
    "observed_new_version": observed_new,
    "old_asset": old_asset,
    "new_asset": new_asset,
    "work_dir": work_dir,
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
