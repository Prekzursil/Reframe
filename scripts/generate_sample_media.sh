#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/samples}"

FFMPEG_BIN="${FFMPEG_BIN:-}"
if [[ -z "${FFMPEG_BIN}" ]]; then
  if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_BIN="$(command -v ffmpeg)"
  elif [[ -x "${ROOT_DIR}/.tools/bin/ffmpeg" ]]; then
    FFMPEG_BIN="${ROOT_DIR}/.tools/bin/ffmpeg"
  else
    echo "ffmpeg not found. Run: make tools-ffmpeg"
    exit 1
  fi
fi

mkdir -p "${OUT_DIR}"

VIDEO_OUT="${OUT_DIR}/sample.mp4"
AUDIO_OUT="${OUT_DIR}/sample.aac"
SRT_OUT="${OUT_DIR}/sample.srt"

echo "Generating ${VIDEO_OUT} ..."
"${FFMPEG_BIN}" -y -v error \
  -f lavfi -i "color=c=black:s=640x360:d=6" \
  -f lavfi -i "sine=frequency=880:duration=6" \
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac \
  "${VIDEO_OUT}"

echo "Generating ${AUDIO_OUT} ..."
"${FFMPEG_BIN}" -y -v error \
  -f lavfi -i "sine=frequency=440:duration=6" \
  -c:a aac \
  "${AUDIO_OUT}"

cat > "${SRT_OUT}" <<'EOF'
1
00:00:00,000 --> 00:00:02,000
Hello from Reframe sample media

2
00:00:02,000 --> 00:00:04,000
Use this for styled subtitle burn-in tests

3
00:00:04,000 --> 00:00:06,000
Offline-first pipeline
EOF

echo ""
echo "Done:"
echo "  ${VIDEO_OUT}"
echo "  ${AUDIO_OUT}"
echo "  ${SRT_OUT}"
echo ""
echo "Next:"
echo "  1) Start the stack: docker compose -f infra/docker-compose.yml up --build"
echo "  2) Upload ${VIDEO_OUT} as a video asset in the UI (or via /api/v1/assets/upload)."
