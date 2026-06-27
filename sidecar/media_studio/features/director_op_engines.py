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
from media_studio.features import reframe as _reframe
from media_studio.features import shorts as _shorts
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

#: Default reframe target aspect when an op omits ``params['aspect']`` (the
#: contract's 1080x1920 vertical short).
DEFAULT_REFRAME_ASPECT = "9:16"

#: atempo accepts a single tempo in [0.5, 2.0]; factors outside are realised by
#: chaining atempo stages (e.g. 4x -> ``atempo=2.0,atempo=2.0``). These bound one
#: stage; :func:`_atempo_chain` decomposes any positive factor into legal stages.
_ATEMPO_MIN = 0.5
_ATEMPO_MAX = 2.0

#: The op kinds wired to a real ffmpeg engine: the core renderers (trim/cut/
#: removeSilence/caption) PLUS the ffmpeg-achievable Director ops added here.
#: Every one of these renders REAL edited media (not a manifest no-op) over the
#: COPY and records a restore-inverse for undo.
WIRED_KINDS: tuple[str, ...] = (
    "trim",
    "cut",
    "join",
    "removeSilence",
    "caption",
    "removeFillers",
    "reframe",
    "zoomPan",
    "retime",
    "overlayText",
    "lowerThird",
    "translateCaption",
    "export",
)

#: The op kinds NOT wired to a real engine — each needs a subsystem ffmpeg alone
#: cannot provide. Logged up front (never silently skipped) so an op of one of
#: these kinds surfaces as a clear per-op ``failed`` with auto-rollback (the
#: graceful degradation), never a silent no-op. HONESTLY DEFERRED:
#:
#:   * ``stitchPanorama`` -> the panorama/stitch engine (multi-frame mosaic);
#:   * ``ocrExtractList``  -> an OCR engine (text recognition, not a render);
#:   * ``regenScroll``     -> the scroll-regen engine (also needs a panorama).
#:
#: ``reorder`` is a multi-clip timeline permutation outside the single-clip
#: render scope of these adapters and is likewise left deferred.
DEFERRED_KINDS: tuple[str, ...] = (
    "reorder",
    "stitchPanorama",
    "regenScroll",
    "ocrExtractList",
)

#: Each deferred kind -> the subsystem it requires. Surfaced verbatim in the
#: deferral notice (:func:`log_deferred`) so the unwired set names WHY each is
#: held back, not just THAT it is.
DEFERRED_SUBSYSTEMS: dict[str, str] = {
    "reorder": "the timeline clip-reorder engine (multi-clip permutation)",
    "stitchPanorama": "the panorama/stitch engine",
    "regenScroll": "the scroll-regen engine (requires a stitched panorama)",
    "ocrExtractList": "an OCR engine",
}


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


def _require_clips(op: EditOp) -> list[str]:
    """Return the join op's ``params['clips']`` — a non-empty list of path strings.

    ``join``/concat appends one or more extra clips AFTER the COPY source, so it
    needs at least one additional clip path. A missing / empty / non-string list
    is a render error (per-op ``failed`` + rollback), never a silent no-op.
    """
    raw = op.params.get("clips")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise DirectorEngineError(f"join op {op.id!r} requires a non-empty params['clips'] list")
    clips = [p for p in raw if isinstance(p, str) and p.strip()]
    if not clips:
        raise DirectorEngineError(f"join op {op.id!r} params['clips'] has no usable path strings")
    return clips


def build_join_argv(
    in_path: str,
    clips: Sequence[str],
    out_path: str,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv that CONCATENATES ``in_path`` + each ``clips`` entry into one mp4.

    Uses ffmpeg's ``concat`` filter (re-encode), which — unlike the concat
    *demuxer* — tolerates inputs whose codecs/resolutions differ, the common case
    when a user joins arbitrary clips. Every input contributes one video + one
    audio stream to the ``concat=n=N:v=1:a=1`` graph, so the output duration is
    the sum of the parts (the strongest non-no-op proof). Output is H.264/AAC.
    """
    inputs = [in_path, *clips]
    n = len(inputs)
    argv = [_ffmpeg.ffmpeg_path(settings), "-hide_banner", "-nostdin", "-y"]
    for path in inputs:
        argv += ["-i", path]
    streams = "".join(f"[{idx}:v][{idx}:a]" for idx in range(n))
    filtergraph = f"{streams}concat=n={n}:v=1:a=1[v][a]"
    argv += [
        "-filter_complex",
        filtergraph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]
    return argv


def make_join_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``join``: concatenate extra ``params['clips']`` after the source.

    Forward renders a real concatenated mp4 (``build_join_argv`` — concat filter,
    re-encode) and re-points the COPY at it; the recorded inverse restores the
    pre-join reference (undo, no re-render). A whole-timeline op (no span).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        clips = _require_clips(op)
        return _render(
            project_copy,
            op,
            lambda i, o: build_join_argv(i, clips, o, settings),
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
        result_path, _removed, _keeps = _silencetrim.trim_clip(
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


def _burn_track_engine(
    op: EditOp,
    project_copy: ProjectCopy,
    *,
    runner: RunFn,
    settings: Mapping[str, Any] | None,
) -> EditOp:
    """Burn the op's target-track cues into the video (libass) + record the inverse.

    The shared forward path for ``caption`` AND ``translateCaption``: both name an
    existing track (validate-and-reject guarantees it) whose inline cues hold the
    burnable text — the ORIGINAL cues for ``caption``, the TRANSLATED cues for
    ``translateCaption`` (the translation having been produced upstream by
    ``subtitles.translate``, which preserves cue timings/indices and rewrites
    each cue's ``text``). Whatever text the named track carries is what gets
    burned, so re-burning a translated track is a real, non-no-op render.
    """
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


def make_caption_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``caption``: BURN the target track's cues into the video (libass).

    Forward builds an ASS document from the track's cues (``caption.build_ass``)
    and hardcodes it onto the video via ``caption.build_burn_argv`` (the same
    libass path ``caption.apply`` ships), re-pointing the COPY at the burned mp4.
    The inverse restores the pre-burn reference (undo, no re-render).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        return _burn_track_engine(op, project_copy, runner=runner, settings=settings)

    return engine


def make_translate_caption_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``translateCaption``: RE-BURN the target track's TRANSLATED cues.

    Identical render path to ``caption`` (``_burn_track_engine``): the named track
    already carries the translated cue text (produced by ``subtitles.translate``
    upstream — it preserves timings and rewrites ``text``), so burning that track
    hardcodes the translated subtitles onto the video. The translation generation
    itself is a separate provider-backed job and is NOT re-done here; this op only
    renders the translated cues that already exist on the track. The inverse
    restores the pre-burn reference (undo, no re-render).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        return _burn_track_engine(op, project_copy, runner=runner, settings=settings)

    return engine


# --------------------------------------------------------------------------- #
# geometry / timing / overlay ops (ffmpeg-achievable Director ops)
# --------------------------------------------------------------------------- #
def _escape_drawtext(text: str) -> str:
    r"""Escape ``text`` for an ffmpeg ``drawtext=text=`` value.

    drawtext's parser treats ``\``, ``:``, ``%`` and ``'`` specially (distinct
    from libass' ``subtitles=`` path escaping). Backslash first, then the rest,
    so a single literal char never double-escapes. Newlines are dropped (drawtext
    is single-line; multi-line lower-thirds use separate ops).
    """
    out = text.replace("\\", "\\\\")
    out = out.replace(":", "\\:")
    out = out.replace("%", "\\%")
    out = out.replace("'", "\\'")
    return out.replace("\n", " ").replace("\r", " ")


def _require_text(op: EditOp) -> str:
    """Return the op's ``params['text']`` (a non-empty string) or a render error."""
    text = op.params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise DirectorEngineError(f"{op.kind!r} op {op.id!r} requires non-empty params['text']")
    return text


def _aspect_ratio(aspect: str) -> tuple[int, int]:
    """Parse a ``"W:H"`` (or ``"WxH"``) aspect string into a positive ``(w, h)``.

    A render error for anything malformed, so a bad ``params['aspect']`` degrades
    to a per-op ``failed`` + rollback rather than a broken filtergraph.
    """
    raw = str(aspect).strip().replace("x", ":")
    parts = raw.split(":")
    if len(parts) != 2:
        raise DirectorEngineError(f"reframe aspect must be 'W:H', got {aspect!r}")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise DirectorEngineError(f"reframe aspect must be two integers, got {aspect!r}") from None
    if w <= 0 or h <= 0:
        raise DirectorEngineError(f"reframe aspect components must be positive, got {aspect!r}")
    return w, h


def build_reframe_argv(
    in_path: str,
    out_path: str,
    aspect: str,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv that CENTER-CROPS ``in_path`` to ``aspect`` then scales to the canvas.

    A pure in-engine crop+scale (NO ``wsl bash`` host bridge): ``crop`` carves a
    centered ``aspect``-ratio window out of the source frame (driven by ``ih`` so
    it works for any input size), then ``scale`` resizes it to the contract output
    dimensions for ``aspect`` (:func:`reframe.output_dimensions`, e.g. 1080x1920
    for 9:16). The result has the target aspect's dimensions — a real geometry
    edit, never a no-op. Audio is stream-copied.
    """
    aw, ah = _aspect_ratio(aspect)
    width, height = _reframe.output_dimensions(aspect)
    vf = f"crop=ih*{aw}/{ah}:ih,scale={width}:{height}"
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        vf,
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def build_zoompan_argv(
    in_path: str,
    out_path: str,
    *,
    total_sec: float,
    dims: tuple[int, int] = (0, 0),
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv for a slow Ken-Burns ``zoompan`` push-in over the whole clip.

    ``zoompan`` takes a per-input-frame duration ``d`` (the number of OUTPUT
    frames each input frame expands to); we keep ``d=1`` at a fixed output ``fps``
    so the zoom advances smoothly across the clip rather than stepping. ``z`` ramps
    from 1.0 toward 1.5 (capped), giving a visible push-in — a real motion edit.

    ``zoompan`` defaults its output canvas to 1280x720 when ``s=`` is omitted,
    which would silently rescale (e.g. a 9:16 short -> landscape 720p). So when
    valid source ``dims`` are known we pin ``s=<w>x<h>`` to PRESERVE the source
    frame size; a failed probe ((0, 0)) omits ``s=`` rather than emit ``s=0x0``.
    Audio is stream-copied.
    """
    fps = 30
    frames = max(1, int(round(max(total_sec, 0.0) * fps)))
    # z ramps from 1.0 to 1.5 across ``frames`` output frames; the comma inside
    # min() is escaped (``\\,``) so the filter parser does not read it as an option
    # separator. ``d=1`` + a fixed ``fps`` advance the zoom one step per frame so
    # the push-in is smooth.
    zexpr = f"min(1.0+0.5*on/{frames}\\,1.5)"
    width, height = dims
    size = f":s={width}x{height}" if width > 0 and height > 0 else ""
    vf = f"zoompan=z={zexpr}:d=1{size}:fps={fps}"
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        vf,
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def _atempo_chain(factor: float) -> list[str]:
    """Decompose a positive playback ``factor`` into legal ``atempo`` stages.

    atempo is bounded to [0.5, 2.0] per stage. Speed-ups > 2.0 chain ``atempo=2.0``
    repeatedly (then a final remainder); slow-downs < 0.5 chain ``atempo=0.5``.
    Returns the per-stage tempo strings (e.g. 4.0 -> ['2.0', '2.0']).
    """
    stages: list[str] = []
    remaining = factor
    while remaining > _ATEMPO_MAX:
        stages.append(f"{_ATEMPO_MAX}")
        remaining /= _ATEMPO_MAX
    while remaining < _ATEMPO_MIN:
        stages.append(f"{_ATEMPO_MIN}")
        remaining /= _ATEMPO_MIN
    stages.append(f"{remaining:.6f}")
    return stages


def build_retime_argv(
    in_path: str,
    out_path: str,
    factor: float,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv that RE-TIMES the clip by ``factor`` (video setpts + audio atempo).

    ``factor`` > 1 speeds up (shorter), < 1 slows down (longer). Video PTS scale
    by ``1/factor`` (``setpts=(1/factor)*PTS``); audio tempo is the matching
    ``atempo`` chain so picture and sound stay in sync. The output duration is
    ``source/factor`` — the strongest non-no-op proof.
    """
    inv = 1.0 / factor
    atempo = ",".join(f"atempo={s}" for s in _atempo_chain(factor))
    filtergraph = f"[0:v]setpts={inv:.6f}*PTS[v];[0:a]{atempo}[a]"
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-filter_complex",
        filtergraph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def build_drawtext_argv(
    in_path: str,
    out_path: str,
    text: str,
    *,
    lower_third: bool,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv that draws ``text`` onto the video via the ``drawtext`` filter.

    ``overlayText`` centers the text in the frame; ``lowerThird`` anchors it in a
    lower band over a translucent box (the classic name/title strap). Both rely on
    fontconfig's default face (no ``fontfile`` needed where fontconfig is present);
    the text is escaped for the drawtext parser. Audio is stream-copied.
    """
    safe = _escape_drawtext(text)
    if lower_third:
        draw = (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=h/18:"
            "box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h-h/6"
        )
    else:
        draw = (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=h/12:"
            "borderw=2:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
        )
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        draw,
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def make_remove_fillers_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``removeFillers``: CUT the op's span of filler words (drop it).

    A span op (validate-and-reject guarantees a valid ``span``): the planner sets
    the span to the filler range to excise, so this is the same head+tail keep as
    ``trim`` — the span is removed and the surrounding clip concatenated, shrinking
    the duration (the same dead-air pipeline as ``removeSilence``/``trim``). The
    inverse restores the pre-cut reference (undo, no re-render).
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


def make_reframe_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``reframe``: center-crop+scale to the target aspect (in-engine).

    Forward renders a real reframed mp4 (``build_reframe_argv`` — crop+scale, NO
    host->WSL bridge) at the contract dimensions for ``params['aspect']`` (default
    9:16), re-pointing the COPY at it. The inverse restores the pre-reframe ref.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        aspect = op.params.get("aspect")
        aspect = aspect if isinstance(aspect, str) and aspect.strip() else DEFAULT_REFRAME_ASPECT
        return _render(
            project_copy,
            op,
            lambda i, o: build_reframe_argv(i, o, aspect, settings),
            runner=runner,
            settings=settings,
        )

    return engine


def make_zoom_pan_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``zoomPan``: apply a Ken-Burns ``zoompan`` push-in (motion).

    Forward renders a real zoom/pan mp4 (``build_zoompan_argv``) over the clip and
    re-points the COPY at it. The inverse restores the pre-zoom reference.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        in_path = _source_path(project_copy)
        total = _ffmpeg.ffprobe_duration(in_path, dict(settings or {}))
        dims = _shorts.probe_dims(in_path, dict(settings or {}))
        return _render(
            project_copy,
            op,
            lambda i, o: build_zoompan_argv(i, o, total_sec=total, dims=dims, settings=settings),
            runner=runner,
            settings=settings,
        )

    return engine


def make_retime_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``retime``: change playback speed by ``params['factor']``.

    Forward renders a real re-timed mp4 (``build_retime_argv`` — setpts + atempo),
    re-pointing the COPY. A non-positive or 1.0 factor is a no-op and rejected as a
    render error. The inverse restores the pre-retime reference.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        raw = op.params.get("factor")
        try:
            factor = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise DirectorEngineError(f"retime op {op.id!r} requires a numeric params['factor']") from None
        if factor <= 0.0 or factor == 1.0:
            raise DirectorEngineError(f"retime factor {factor!r} is a no-op (must be > 0 and != 1.0)")
        return _render(
            project_copy,
            op,
            lambda i, o: build_retime_argv(i, o, factor, settings),
            runner=runner,
            settings=settings,
        )

    return engine


def make_overlay_text_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``overlayText``: draw ``params['text']`` centered (drawtext).

    Forward renders a real mp4 with the text burned in (``build_drawtext_argv``)
    and re-points the COPY. The inverse restores the pre-overlay reference.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        text = _require_text(op)
        return _render(
            project_copy,
            op,
            lambda i, o: build_drawtext_argv(i, o, text, lower_third=False, settings=settings),
            runner=runner,
            settings=settings,
        )

    return engine


def make_lower_third_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``lowerThird``: draw ``params['text']`` as a lower-third strap.

    Forward renders a real mp4 with a boxed lower-band caption (``build_drawtext_argv``
    ``lower_third=True``) and re-points the COPY. The inverse restores the prior ref.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        text = _require_text(op)
        return _render(
            project_copy,
            op,
            lambda i, o: build_drawtext_argv(i, o, text, lower_third=True, settings=settings),
            runner=runner,
            settings=settings,
        )

    return engine


def make_export_engine(*, runner: RunFn, settings: Mapping[str, Any] | None = None) -> OpEngine:
    """Engine for ``export``: re-encode/mux the timeline to a delivery mp4.

    A whole-timeline op (no span): re-encodes the current COPY source to H.264/AAC
    (``ffmpeg.build_convert_argv``), producing a fresh, ffprobe-valid delivery file
    the COPY is re-pointed at. The inverse restores the pre-export reference.
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        restored = _maybe_restore(op, project_copy)
        if restored is not None:
            return restored
        return _render(
            project_copy,
            op,
            lambda i, o: _ffmpeg.build_convert_argv(i, o, {"vcodec": "libx264", "acodec": "aac"}, dict(settings or {})),
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
        "join": make_join_engine(runner=run, settings=settings),
        "removeSilence": make_remove_silence_engine(runner=run, settings=settings),
        "caption": make_caption_engine(runner=run, settings=settings),
        "removeFillers": make_remove_fillers_engine(runner=run, settings=settings),
        "reframe": make_reframe_engine(runner=run, settings=settings),
        "zoomPan": make_zoom_pan_engine(runner=run, settings=settings),
        "retime": make_retime_engine(runner=run, settings=settings),
        "overlayText": make_overlay_text_engine(runner=run, settings=settings),
        "lowerThird": make_lower_third_engine(runner=run, settings=settings),
        "translateCaption": make_translate_caption_engine(runner=run, settings=settings),
        "export": make_export_engine(runner=run, settings=settings),
    }


def log_deferred(log: Any) -> None:
    """Log the wired kinds + the deferred kinds WITH the subsystem each requires.

    Called once when the table is built so a deferred-kind op's eventual per-op
    ``failed`` is never a surprise — the unwired set is announced up front, each
    annotated with the subsystem (``DEFERRED_SUBSYSTEMS``) ffmpeg cannot supply,
    so the notice reads "requires <subsystem>" rather than a bare kind name.
    """
    requires = "; ".join(f"{kind} (requires {DEFERRED_SUBSYSTEMS[kind]})" for kind in DEFERRED_KINDS)
    log.info("director.apply real engines wired for %s; deferred (no engine yet): %s", WIRED_KINDS, requires)


__all__ = [
    "DEFERRED_KINDS",
    "DEFERRED_SUBSYSTEMS",
    "WIRED_KINDS",
    "RESTORE_KEY",
    "DirectorEngineError",
    "build_drawtext_argv",
    "build_engines",
    "build_join_argv",
    "build_reframe_argv",
    "build_retime_argv",
    "build_zoompan_argv",
    "log_deferred",
    "make_caption_engine",
    "make_cut_engine",
    "make_export_engine",
    "make_join_engine",
    "make_lower_third_engine",
    "make_overlay_text_engine",
    "make_reframe_engine",
    "make_remove_fillers_engine",
    "make_remove_silence_engine",
    "make_retime_engine",
    "make_translate_caption_engine",
    "make_trim_engine",
    "make_zoom_pan_engine",
]
