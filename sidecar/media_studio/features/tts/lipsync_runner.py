"""Lip-sync relip runner — executes INSIDE the isolated env (WU-B1).

Invoked by :class:`..tts.lipsync.SubprocessLipSyncBackend` as::

    <env_python> -m lipsync_runner <job.json>

with ``PYTHONPATH`` pointing at the pip ``--target`` env (torch, diffusers,
the LatentSync/MuseTalk package) plus this directory. It is NOT part of the
sidecar's runtime import graph: the file lives in the package only so it ships
with the app, and the module is import-light by design — **all heavy imports
happen inside :func:`_relip`**, never at import time, so pytest collection and
the sidecar process never load them (mirrors :mod:`.chatterbox_runner`).

Job document (written by ``lipsync.build_relip_job_payload``)::

    {"videoPath": str, "audioPath": str, "outVideo": str,
     "engine": "latentsync"|"musetalk", "quality": "fast"|"quality",
     "boxes": [[x, y, w, h], ...]}

``boxes`` are per-frame face rects from the already-shipped MIT YuNet detector.
When present the backend MUST use them instead of its bundled detector: the
upstream MuseTalk-class graph pulls S3FD, which ships with NO LICENCE at all
(plan §3.4) — so passing our own boxes is a licence requirement, not a perf
tweak.

Output: one video at ``outVideo`` whose mouth region matches ``audioPath``.
Errors print to stderr and exit non-zero (the backend surfaces the tail through
the job.done error payload).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# STANDALONE BY CONTRACT: this module is executed as the TOP-LEVEL module
# ``lipsync_runner`` inside the isolated env (``-m lipsync_runner``), so it has
# no package context and CANNOT import ``.lipsync`` — a relative import here
# would raise ``ImportError: attempted relative import with no known parent
# package`` at runtime while unit-testing green from the sidecar env, exactly the
# both-states blind spot. The selector literals are therefore duplicated, and
# ``test_tts_lipsync.py`` asserts they still equal ``lipsync.QUALITIES`` /
# ``lipsync.DEFAULT_QUALITY`` so the duplication cannot silently drift.
QUALITIES: tuple[str, ...] = ("fast", "quality")
DEFAULT_QUALITY = "quality"


def parse_job(raw: Any) -> dict[str, Any]:
    """Validate the job document (pure; unit-tested from the sidecar env)."""
    if not isinstance(raw, dict):
        raise ValueError("job must be a JSON object")
    for key in ("videoPath", "audioPath", "outVideo"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"job.{key} (str) is required")
    engine = raw.get("engine")
    if not isinstance(engine, str) or not engine:
        raise ValueError("job.engine (str) is required")
    quality = raw.get("quality")
    if quality not in QUALITIES:
        # An unknown/absent selector degrades to the safe default rather than
        # failing a job that is otherwise fully specified.
        quality = DEFAULT_QUALITY
    raw_boxes = raw.get("boxes", [])
    if not isinstance(raw_boxes, list):
        raise ValueError("job.boxes must be an array of [x, y, w, h]")
    boxes: list[tuple[int, int, int, int]] = []
    for box in raw_boxes:
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("job.boxes entries must be [x, y, w, h]")
        x, y, w, h = (int(v) for v in box)
        boxes.append((x, y, w, h))
    return {
        "videoPath": str(raw["videoPath"]),
        "audioPath": str(raw["audioPath"]),
        "outVideo": str(raw["outVideo"]),
        "engine": engine,
        "quality": quality,
        "boxes": boxes,
    }


def _relip(job: dict[str, Any]) -> None:  # pragma: no cover - isolated env only
    """The heavy path — runs ONLY in the lip-sync env (torch + diffusers present).

    NOT-CHECKED end-to-end: this body has never been executed in this lane (no
    GPU and no downloaded OpenRAIL weights on the build box), so nothing here
    may be cited as "working". The settling experiment is the opt-in ``@e2e``
    tier of plan §4 WU-A7/WU-B1: real weights + real footage + a SyncNet/LSE-C
    confidence score measured across the WHOLE timeline.
    """
    import torch  # noqa: PLC0415
    from latentsync.pipelines.lipsync_pipeline import (
        LipsyncPipeline,  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    steps = 20 if job["quality"] == "quality" else 8
    pipeline = LipsyncPipeline.from_pretrained(job["engine"]).to(device)
    out = Path(job["outVideo"])
    out.parent.mkdir(parents=True, exist_ok=True)
    pipeline(
        video_path=job["videoPath"],
        audio_path=job["audioPath"],
        video_out_path=str(out),
        num_inference_steps=steps,
        face_boxes=job["boxes"] or None,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry: read <job.json>, re-lip, exit 0 on success."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m lipsync_runner <job.json>", file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        job = parse_job(raw)
    except (OSError, ValueError) as exc:
        print(f"lipsync_runner: bad job file: {exc}", file=sys.stderr)
        return 2
    try:
        _relip(job)
    except Exception as exc:  # noqa: BLE001 - report any failure on stderr
        print(f"lipsync_runner: relip failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry
    raise SystemExit(main())
