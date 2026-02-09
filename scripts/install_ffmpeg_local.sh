#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${ROOT_DIR}/.tools"
BIN_DIR="${TOOLS_DIR}/bin"
FFMPEG_DIR="${TOOLS_DIR}/ffmpeg"

mkdir -p "${BIN_DIR}" "${FFMPEG_DIR}"

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg + ffprobe already available on PATH"
  exit 0
fi

ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"

if [[ "${OS}" != "linux" ]]; then
  echo "This installer currently supports linux only. Please install ffmpeg via your system package manager."
  exit 1
fi

if [[ "${ARCH}" != "x86_64" && "${ARCH}" != "amd64" ]]; then
  echo "Unsupported arch: ${ARCH} (expected x86_64/amd64)."
  exit 1
fi

TARBALL="${FFMPEG_DIR}/ffmpeg-release-amd64-static.tar.xz"
URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

echo "Downloading ffmpeg static build..."
curl -L --fail -o "${TARBALL}" "${URL}"

echo "Extracting..."
tar -xf "${TARBALL}" -C "${FFMPEG_DIR}"

EXTRACTED_DIR="$(find "${FFMPEG_DIR}" -maxdepth 1 -type d -name 'ffmpeg-*-amd64-static' | sort | tail -n 1)"
if [[ -z "${EXTRACTED_DIR}" ]]; then
  echo "Failed to locate extracted ffmpeg directory."
  exit 1
fi

ln -sf "${EXTRACTED_DIR}/ffmpeg" "${BIN_DIR}/ffmpeg"
ln -sf "${EXTRACTED_DIR}/ffprobe" "${BIN_DIR}/ffprobe"

echo "Installed local ffmpeg tools:"
echo "  ${BIN_DIR}/ffmpeg"
echo "  ${BIN_DIR}/ffprobe"
echo ""
echo "Run tests with:"
echo "  PATH=\"${BIN_DIR}:\$PATH\" PYTHONPATH=.:apps/api:packages/media-core/src .venv/bin/python -m pytest apps/api/tests services/worker packages/media-core/tests"

