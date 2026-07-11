"""run_export progress stays forward-only across stage notices (bug-sweep fix).

A mid-export stage notice (e.g. the default-on stabilize libvidstab-unavailable
notice, or a reframe speaker-tracking degrade) used to call ctx.progress(4, ...),
snapping the progress bar backward to 4% from wherever the export had reached.
It now reports the notice at the loop's current percent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.features import shortmaker as sm


class _RecCtx:
    cancelled = False

    def __init__(self) -> None:
        self.events: list[tuple[int, str]] = []

    def progress(self, pct: int, msg: str) -> None:
        self.events.append((int(pct), msg))

    def raise_if_cancelled(self) -> None:  # pragma: no cover - never cancelled here
        ...


def test_export_stage_notice_does_not_reset_progress(tmp_path: Path) -> None:
    calls = [0]

    def stabilize(in_p: str, out_p: str, *, settings: Any = None, on_notice: Any = None) -> str:
        calls[0] += 1
        if calls[0] == 3 and on_notice:  # emit on clip 3 (already ~40% in)
            on_notice({"type": "libvidstab", "message": "NOTICE"})
        return in_p

    stages = sm.Stages(
        cut_clip=lambda in_p, out_p, s, e, *, settings=None: out_p,
        stabilize=stabilize,
        reframe=lambda i, o, a, *, settings=None, on_notice=None: o,
        render_caption=lambda *a, **k: a[2],
        export_clip=lambda i, o, *, settings=None: o,
    )
    cands = [
        {"rank": r, "start": 0.0, "end": 5.0, "durationSec": 5.0, "sourceStart": 0.0, "hook": "", "why": "", "score": 1}
        for r in range(1, 6)
    ]
    ctx = _RecCtx()
    sm.run_export(
        ctx,
        video_id="v",
        candidates=cands,
        load_context=lambda vid: {"path": str(tmp_path / "src.mp4"), "transcript": {"segments": []}},
        out_dir=str(tmp_path / "o"),
        stages=stages,
    )
    notice_pcts = [pct for pct, msg in ctx.events if msg == "NOTICE"]
    assert notice_pcts, "the stage notice was never surfaced"
    assert notice_pcts[0] != 4, "a stage notice reset export progress to 4%"
    assert notice_pcts[0] >= 20, "the notice should show at the current export percent (clip 3 of 5)"
