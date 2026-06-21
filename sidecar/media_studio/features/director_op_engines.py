"""Real ffmpeg op-engine adapters for ``director.apply`` (FIX #7, WU-apply).

``apply_engine.apply_plan`` walks an :class:`EditPlan` over a project COPY and
dispatches each op to an injected ``{kind: engine}`` table (the seam). v1 shipped
that table EMPTY (``handlers._director_engines`` returned ``{}``), so EVERY op hit
the "no engine for kind" path -> ``failed`` -> auto-rollback, and a real client
got a no-op manifest copy instead of an edited mp4. This module supplies the REAL
adapters that table needs, so ``director.apply`` actually renders edited media.

Each adapter is an :data:`apply_engine.OpEngine` — ``(EditOp, ProjectCopy) -> EditOp``
— that:

  * reads the COPY's current source video (``data["video"]["path"]``) — NEVER the
    untouched source manifest;
  * renders a REAL edited mp4 (reusing the shipped ffmpeg helpers:
    ``fillers.build_segment_cut_argv`` for span keeps/cuts, ``silencetrim.trim_clip``
    for dead-air removal, ``caption.build_ass`` + ``caption.build_burn_argv`` for
    subtitle burn-in) into the COPY's ``.director-copy`` folder, beside the COPY
    manifest;
  * re-points the COPY manifest at the rendered file and returns an INVERSE op
    that restores the prior reference (no re-render), so ``director.undo`` round-trips.

DUAL-MODE (forward + inverse over the SAME kind): the recorded inverse op routes
back through ``engines[kind]`` during rollback/undo (``apply_plan`` /
``_director_inverse_engines``). An inverse op is tagged with the sentinel
:data:`RESTORE_KEY` in its params; an adapter seeing that sentinel just RESTORES
the recorded reference and returns the re-inverse — it never re-renders. This
mirrors the ``params['undo']`` precedent in ``test_apply_engine``.

PURITY / SEAM: the ONE impure thing — the ffmpeg subprocess — is the injected
``runner`` (default :func:`ffmpeg.run`). Unit tests inject a fake runner that
stubs the output file (covers the dispatch/manifest/inverse logic + every error
branch deterministically); a separate ``@pytest.mark.integration`` test uses the
real runner to prove a ffprobe-valid edited mp4 + undo round-trip. No
``Provider``/transport/heavy-ML import.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from media_studio import ffmpeg as _ffmpeg
from media_studio.features import caption as _caption
from media_studio.features import fillers as _fillers
from media_studio.features import silencetrim as _silencetrim
from media_studio.features.apply_engine import EngineTable, OpEngine
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp

#: A runner ``(argv, total_sec) -> exit_code`` — the injected ffmpeg subprocess
#: seam. Default :func:`ffmpeg.run`; tests inject a fake that stubs the output.
RunFn = Callable[..., int]

#: The inverse-op sentinel param: when present in ``op.params`` it carries the
#: video path to RESTORE, so an adapter knows this is the undo direction (restore,
#: never re-render). Double-underscored so it can never collide with a planner param.
RESTORE_KEY = "__directorRestoreVideo__"

#: The op kinds wired to a real ffmpeg engine in v1 (the core renderers).
WIRED_KINDS: tuple[str, ...] = ("trim", "cut", "removeSilence", "caption")

#: The op kinds NOT yet wired to a real engine in v1 — logged (never silently
#: skipped) so an op of one of these kinds surfaces as a clear per-op ``failed``
#: with auto-rollback. ``reframe`` is held back deliberately: its shipped helper
#: shells ``wsl bash <script>`` (a host->WSL bridge), which is not a portable
#: in-engine render path; the rest are manifest/track/multi-artifact ops out of
#: the v1 render scope. (``export`` re-encodes the whole timeline; that lands with
#: the export WU.)
DEFERRED_KINDS: tuple[str, ...] = (
    "removeFillers",
    "reorder",
    "retime",
    "reframe",
    "zoomPan",
    "translateCaption",
    "overlayText",
    "lowerThird",
    "export",
    "stitchPanorama",
    "regenScroll",
    "ocrExtractList",
)


class DirectorEngineError(RuntimeError):
    """Raised when a real op-engine cannot render (bad manifest / ffmpeg failure).

    ``apply_plan`` captures this as the op's ``status="failed"`` + reason and
    auto-rolls-back the COPY (the source manifest was never touched), so a render
    failure degrades to a no-op edit, never a crash or a corrupt source.
    """


def _video_block(project_copy: ProjectCopy) -> dict[str, Any]:
    """Return the COPY manifest's mutable ``video`` block (the edited ref lives here)."""
    video = project_copy.data.get("video")
    if not isinstance(video, dict):
        raise DirectorEngineError("project copy has no 'video' block to edit")
    return video


def _source_path(project_copy: ProjectCopy) -> str:
    """Return the COPY's current source video path (what the next op renders FROM)."""
    path = _video_block(project_copy).get("path")
    if not isinstance(path, str) or not path:
        raise DirectorEngineError("project copy 'video' has no source path")
    return path


def _out_path(project_copy: ProjectCopy, op: EditOp) -> Path:
    """Resolve a deterministic, per-op output mp4 path inside the COPY folder.

    The render is written BESIDE the COPY manifest (the isolated ``.director-copy``
    folder), so it can never overwrite the source and persists for undo (which
    re-points to it without re-rendering).
    """
    folder = project_copy.manifest_path.parent
    src_stem = Path(_source_path(project_copy)).stem
    return folder / f"{src_stem}.{op.id}.mp4"


def _repoint(project_copy: ProjectCopy, new_path: str) -> str:
    """Point the COPY manifest's video at ``new_path`` AND PERSIST it; return the old path.

    Re-pointing only the in-memory ``data`` is not enough: a real client reads the
    rendered result from the COPY manifest ON DISK (``ApplyResult.project_copy_path``,
    which ``copy_project`` wrote ONCE at copy time still pointing at the SOURCE). So
    we re-write the manifest here — on BOTH the forward render and the undo restore —
    so the persisted manifest references the rendered edit (forward) or flips back to
    the source (undo). Without this the edited bytes exist but are orphaned: the
    returned manifest would still reference the unedited source (the marquee no-op).
    """
    video = _video_block(project_copy)
    old_path = str(video.get("path") or "")
    video["path"] = new_path
    project_copy.manifest_path.write_text(json.dumps(project_copy.data, indent=2, ensure_ascii=False), encoding="utf-8")
    return old_path


def _inverse_op(op: EditOp, restore_path: str) -> EditOp:
    """Build the recorded inverse op: same id/kind, carrying the path to restore.

    Re-feeding this op through the SAME-kind adapter (rollback/undo) restores the
    pre-op video reference. Marked ``reversible`` so the undo walk is never gated.
    """
    return EditOp(
        id=op.id,
        kind=op.kind,
        span=op.span,
        params={RESTORE_KEY: restore_path},
        reversible=True,
        rationale=op.rationale,
    )


def _maybe_restore(op: EditOp, project_copy: ProjectCopy) -> EditOp | None:
    """If ``op`` is an inverse op (carries the sentinel), restore + return re-inverse.

    Returns the re-inverse op (so a double-undo is itself reversible) when this is
    the undo direction, or ``None`` when this is a fresh forward op to render.
    """
    restore = op.params.get(RESTORE_KEY)
    if not isinstance(restore, str):
        return None
    previous = _repoint(project_copy, restore)
    return _inverse_op(op, previous)


def _render(
    project_copy: ProjectCopy,
    op: EditOp,
    build_argv: Callable[[str, str], list[str]],
    *,
    runner: RunFn,
    settings: Mapping[str, Any] | None,
) -> EditOp:
    """Render via ``build_argv(in, out)`` over the COPY source; re-point + record inverse.

    The common forward path for the span/cut renderers: probe the source duration
    (for progress %), run the built argv through the injected ``runner``, and on a
    clean exit re-point the manifest at the rendered file. A non-zero exit raises
    :class:`DirectorEngineError` (captured as the op's ``failed`` status upstream).
    """
    in_path = _source_path(project_copy)
    out_path = _out_path(project_copy, op)
    argv = build_argv(in_path, str(out_path))
    total = _ffmpeg.ffprobe_duration(in_path, dict(settings or {}))
    code = runner(argv, total_sec=total)
    if code != 0:
        raise DirectorEngineError(f"ffmpeg exit {code} rendering {op.kind!r} op {op.id!r}")
    previous = _repoint(project_copy, str(out_path))
    return _inverse_op(op, previous)


def _require_span(op: EditOp) -> tuple[int, int]:
    """Return the op's span in ms (validate-and-reject guarantees it is present/valid)."""
    if op.span is None:  # pragma: no cover - validate_and_reject drops span-less span ops first
        raise DirectorEngineError(f"{op.kind!r} op {op.id!r} requires a span")
    return op.span


def _keep_for_trim(op: EditOp, total_sec: float) -> list[tuple[float, float]]:
    """Keeps for a ``trim`` op: drop the span, keep everything outside it.

    ``trim`` removes the dead-air / unwanted range ``[start, end]`` and keeps the
    head ``[0, start)`` + tail ``(end, total]`` (whichever are non-empty). A span
    covering the whole clip would leave nothing — guarded as a render error.
    """
    span = _require_span(op)
    start_s = span[0] / 1000.0
    end_s = span[1] / 1000.0
    keeps: list[tuple[float, float]] = []
    if start_s > 0.0:
        keeps.append((0.0, start_s))
    if end_s < total_sec:
        keeps.append((end_s, total_sec))
    if not keeps:
        raise DirectorEngineError("trim span covers the whole clip (nothing left to keep)")
    return keeps


def _keep_for_cut(op: EditOp) -> list[tuple[float, float]]:
    """Keeps for a ``cut`` op: keep ONLY the span ``[start, end]`` (discard the rest)."""
    span = _require_span(op)
    return [(span[0] / 1000.0, span[1] / 1000.0)]


def make_trim_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``trim``: re-cut the clip with the span REMOVED (dead-air drop).

    Forward renders a real mp4 (head + tail concatenated via
    ``fillers.build_segment_cut_argv``) and re-points the COPY at it; the recorded
    inverse restores the pre-trim reference (undo, no re-render).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        in_path = _source_path(project_copy)
        total = _ffmpeg.ffprobe_duration(in_path, dict(settings or {}))
        keeps = _keep_for_trim(op, total)
        return _render(
            project_copy,
            op,
            lambda i, o: _fillers.build_segment_cut_argv(i, o, keeps, dict(settings or {})),
            runner=runner,
            settings=settings,
        )

    return engine


def make_cut_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``cut``: KEEP only the span, discard the rest (extract a sub-clip).

    Forward renders the kept span via ``fillers.build_segment_cut_argv`` and
    re-points the COPY; the inverse restores the pre-cut reference.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        keeps = _keep_for_cut(op)
        return _render(
            project_copy,
            op,
            lambda i, o: _fillers.build_segment_cut_argv(i, o, keeps, dict(settings or {})),
            runner=runner,
            settings=settings,
        )

    return engine


def make_remove_silence_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``removeSilence``: drop sub-threshold dead air (the "silencetrim").

    Reuses the shipped ``silencetrim.trim_clip`` (detect silent spans -> invert to
    keeps -> re-cut), so apply rides the SAME dead-air pipeline as ``silence.trim``.
    When the trim finds nothing to remove it returns the input unchanged; the
    adapter still re-points to a concrete prior reference, so the inverse always
    restores a real path.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        in_path = _source_path(project_copy)
        out_path = _out_path(project_copy, op)
        result_path, _removed = _silencetrim.trim_clip(
            in_path,
            str(out_path),
            settings=dict(settings or {}),
            run=runner,
        )
        previous = _repoint(project_copy, result_path)
        return _inverse_op(op, previous)

    return engine


def _track_cues(project_copy: ProjectCopy, op: EditOp) -> Sequence[Mapping[str, Any]]:
    """Return the cues of the caption op's target track from the COPY manifest.

    ``caption`` is a track-bound op (validate-and-reject guarantees ``params['track']``
    names an EXISTING track), so the burnable content is that track's inline cues
    (``{index, start, end, text}``, the ``subtitles.new_track`` schema). A track
    with no cues cannot burn anything -> a render error (never a silent no-op).
    """
    track_id = op.params.get("track")
    tracks = project_copy.data.get("tracks")
    if isinstance(tracks, Sequence) and not isinstance(tracks, (str, bytes)):
        for track in tracks:
            if isinstance(track, Mapping) and track.get("id") == track_id:
                cues = track.get("cues")
                if isinstance(cues, Sequence) and not isinstance(cues, (str, bytes)) and cues:
                    return [c for c in cues if isinstance(c, Mapping)]
                raise DirectorEngineError(f"caption track {track_id!r} has no cues to burn")
    raise DirectorEngineError(f"caption track {track_id!r} not found in project copy")


def make_caption_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``caption``: BURN the target track's cues into the video (libass).

    Forward builds an ASS document from the track's cues (``caption.build_ass``)
    and hardcodes it onto the video via ``caption.build_burn_argv`` (the same
    libass path ``caption.apply`` ships), re-pointing the COPY at the burned mp4.
    The inverse restores the pre-burn reference (undo, no re-render).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        cues = _track_cues(project_copy, op)
        out_path = _out_path(project_copy, op)
        ass_path = out_path.with_suffix(".ass")
        ass_doc = _caption.build_ass(cues)
        ass_path.write_text(ass_doc, encoding="utf-8")
        return _render(
            project_copy,
            op,
            lambda i, o: _caption.build_burn_argv(i, str(ass_path), o, dict(settings or {})),
            runner=runner,
            settings=settings,
        )

    return engine


def build_engines(*, runner: RunFn | None = None, settings: Mapping[str, Any] | None = None) -> EngineTable:
    """Build the real ``{kind: engine}`` dispatch table for ``director.apply``.

    Closes each adapter over the injected ``runner`` (default :func:`ffmpeg.run`,
    the real subprocess) + ``settings`` (ffmpeg binary resolution). Covers the
    :data:`WIRED_KINDS` core renderers; :data:`DEFERRED_KINDS` are intentionally
    absent (logged by :func:`log_deferred`), so an op of a deferred kind surfaces
    as a per-op ``failed`` with auto-rollback (never a silent no-op).
    """
    run = runner if runner is not None else _ffmpeg.run
    return {
        "trim": make_trim_engine(runner=run, settings=settings),
        "cut": make_cut_engine(runner=run, settings=settings),
        "removeSilence": make_remove_silence_engine(runner=run, settings=settings),
        "caption": make_caption_engine(runner=run, settings=settings),
    }


def log_deferred(log: Any) -> None:
    """Log the op kinds NOT yet wired to a real engine (visibility, never silent).

    Called once when the table is built so a deferred-kind op's eventual per-op
    ``failed`` is never a surprise — the set of unwired kinds is announced up front.
    """
    log.info("director.apply real engines wired for %s; deferred (no engine yet): %s", WIRED_KINDS, DEFERRED_KINDS)


__all__ = [
    "DEFERRED_KINDS",
    "WIRED_KINDS",
    "RESTORE_KEY",
    "DirectorEngineError",
    "build_engines",
    "log_deferred",
    "make_caption_engine",
    "make_cut_engine",
    "make_remove_silence_engine",
    "make_trim_engine",
]
