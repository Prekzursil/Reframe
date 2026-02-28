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

extract_appimage_version() {
  local appimage="$1"
  local fallback="$2"
  local tmp
  tmp="$(mktemp -d)"

  local version=""
  if (cd "$tmp" && "$appimage" --appimage-extract >/dev/null 2>&1); then
    local desktop
    desktop="$(find "$tmp/squashfs-root" -maxdepth 3 -type f -name '*.desktop' | head -n1 || true)"
    if [[ -n "$desktop" && -f "$desktop" ]]; then
      version="$(grep -E '^(X-AppImage-Version|Version)=' "$desktop" | head -n1 | cut -d'=' -f2- | tr -d '\r' || true)"
    fi
  fi

  rm -rf "$tmp"

  if [[ -z "$version" ]]; then
    version="$fallback"
  fi

  echo "$version"
}

if [[ -z "$work_dir" ]]; then
  work_dir="${TMPDIR:-/tmp}/reframe-updater-e2e"
fi
mkdir -p "$work_dir"

old_version="$(version_from_tag "$old_tag")"
new_version="$(version_from_tag "$new_tag")"
old_asset="Reframe_${old_version}_amd64.AppImage"
new_asset="Reframe_${new_version}_amd64.AppImage"

if [[ -z "${GH_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
  export GH_TOKEN="$GITHUB_TOKEN"
fi

gh release download "$old_tag" -R Prekzursil/Reframe -p "$old_asset" -D "$work_dir" --clobber >/dev/null
gh release download "$new_tag" -R Prekzursil/Reframe -p "$new_asset" -D "$work_dir" --clobber >/dev/null

old_path="$work_dir/$old_asset"
new_path="$work_dir/$new_asset"
chmod +x "$old_path" "$new_path"

install_dir="$HOME/.local/share/reframe-updater-e2e"
mkdir -p "$install_dir"
install_path="$install_dir/Reframe.AppImage"

cp "$old_path" "$install_path"
observed_old_version="$(extract_appimage_version "$install_path" "$old_version")"

cp "$new_path" "$install_path"
observed_new_version="$(extract_appimage_version "$install_path" "$new_version")"

python3 - <<'PY' "$old_tag" "$new_tag" "$old_version" "$new_version" "$observed_old_version" "$observed_new_version" "$old_asset" "$new_asset" "$work_dir" "$install_path"
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
    install_path,
) = sys.argv[1:]

payload = {
    "platform": "linux",
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
    "install_path": install_path,
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
