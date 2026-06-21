#!/usr/bin/env bash
# media-studio verthor reframe adapter script (runs under WSL2).
# Argv contract (matches features/reframe.py build_reframe_argv):
#   verthor_reframe.sh <in_wsl_path> <out_wsl_path> <aspect> <width> <height>
# aspect/width/height are advisory: verthor's preset pipeline derives the 9:16
# 1080x1920 geometry itself (verified engine-2 behavior); they are accepted so
# the argv contract stays stable if a future engine needs them.
set -euo pipefail
IN="${1:?usage: verthor_reframe.sh <in> <out> <aspect> <width> <height>}"
OUT="${2:?usage: verthor_reframe.sh <in> <out> <aspect> <width> <height>}"
ASPECT="${3:-9:16}"
WIDTH="${4:-1080}"
HEIGHT="${5:-1920}"

# The existing WSL verthor install (T5 later owns provisioning this).
VENV="$HOME/.local/share/reframe/verthor"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "verthor venv not found at $VENV (run the verthor WSL install)" >&2
  exit 3
fi
source "$VENV/bin/activate"
# cd so the bundled yolo11n-seg.pt weights resolve (verified recipe).
cd /mnt/d/tools/reframe/verthor

# Anti-jump: verthor's motion-damping defaults are already well-tuned (lowering
# them MEASURABLY worsened shake — vidstabdetect 0.88->0.95px). The visible
# "shake" on dynamic sources is FRAMING JUMPS from over-eager scene-cut resets
# (a 23s TV-studio clip reset 5x). Calmer scene detection (higher threshold,
# longer min scene length) cuts the spurious resets; --post-restore eases back
# to the prior framing across a real cut instead of snapping. Env-overridable.
python -m verthor "$IN" "$OUT" \
  --preset talking_head \
  --saliency-model handcrafted \
  --video-encoder libx264 \
  --scene-threshold "${MS_SCENE_THRESHOLD:-8.0}" \
  --min-scene-len "${MS_MIN_SCENE_LEN:-30}" \
  --post-restore

W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$OUT")
H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$OUT")
printf 'REFRAME_OK out=%s %sx%s\n' "$OUT" "$W" "$H"
