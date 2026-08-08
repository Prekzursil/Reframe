"""TRANSCRIPT-NATIVE EDITING — delete a word, the video cuts (v1.5 flagship #2).

The Descript-class vertical slice from ``docs/plans/v1.5/flagship-transcript-editing.md``
(WU-T1 addressing + WU-T3 translator/service). It adds **no new cut math**: every
timeline operation below is the already-shipped, already-covered engine —

* word timings come from ``features/transcribe.py`` (``word_timestamps=True``),
  optionally tightened by ``features/ctc_align.py``;
* filler + silence removal is ``features/refine.plan_refine`` (which itself
  composes ``fillers.build_cutlist_with_stats`` + ``silencetrim.keep_spans``);
* the frame-accurate, ORDER-PRESERVING render is
  ``fillers.build_segment_cut_argv``;
* caption re-timing is ``fillers.remap_cues``.

What is genuinely new is three thin, PURE layers:

1. **Addressing** — :func:`address_transcript` stamps a stable ``wordId``
   (``w{segmentIndex}-{wordIndex}``) onto every word so the renderer can point at
   a token and the backend can resolve it back to ``[start, end]`` seconds. It is
   non-destructive: the input transcript is never mutated, and an already-stamped
   ``wordId`` is preserved so a re-transcription can carry ids forward.
2. **Translation** — :func:`resolve_edits` turns EditSpans into removed spans.
   Like :func:`edit_validate.validate_and_reject` it **never raises**: an
   impossible/unknown/deferred span is DROPPED with a typed reason so the caller
   can surface exactly what was ignored.
3. **Composition** — :func:`plan_transcript_edit` unions the word deletes with
   the refine plan into ONE keep-list, so a delete + filler-strip + silence-trim
   is a SINGLE encode (mirroring ``refine.apply``).

SCOPE (honest): this module ships ``delete`` and ``trim`` — the monotonic
keep-list half. ``reorder`` is DEFERRED (the design's C3 gap; see
``director_op_engines.DEFERRED_KINDS``) and is rejected with
:data:`REASON_REORDER_DEFERRED` rather than silently mis-applied, because the
shipped cue remap (``fillers.remap_time``) assumes MONOTONIC keeps and would
emit wrong times for a reordered span.

REVERSIBILITY: ``applyEdit`` writes a NEW ``*.edited.mp4`` and never touches the
source, then records the edit in ``project["transcriptEdits"]``. ``undoEdit``
pops that record, so the project's current render walks back one edit at a time.
This is a project-level ledger undo, NOT the ``apply_engine``/``director.undo``
manifest walk — routing an ordered EDL through ``apply_engine`` is the deferred
reorder work (WU-T6), and pretending otherwise here would be an overclaim.

NO subprocess, NO model, NO real I/O in the pure half; every heavy seam
(``run``/``duration``/``detect_run``/``load_project``/``save_project``) is
injected exactly as ``RefineService`` does it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict

from .. import protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import fillers as _fillers
from . import refine as _refine
from . import silencetrim as _silencetrim

log = get_logger("media_studio.transcript_edit")

# Injectable seams (identical to refine.RefineService — same shapes, same fakes).
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
DetectRunner = Callable[..., Any]
Resolver = Callable[[str], str | None]
LoadProject = Callable[[str], dict[str, Any]]
SaveProject = Callable[[str, dict[str, Any]], None]

#: A removed/kept span in ORIGINAL-video seconds.
Span = tuple[float, float]

#: The project key holding the reversible edit ledger (see ``library.Project``).
EDITS_KEY = "transcriptEdits"

# --- typed drop reasons (mirrors edit_validate's "drop with a reason" contract) ---
#: The op name is not one this module implements.
REASON_UNKNOWN_OP = "unknown-op"
#: ``reorder`` is the design's ONE deferred backend gap (C3 / WU-T6).
REASON_REORDER_DEFERRED = "reorder-deferred"
#: The addressed word does not exist in this transcript.
REASON_UNKNOWN_WORD = "unknown-word"
#: Neither a resolvable word address nor explicit ``startMs``/``endMs`` bounds.
REASON_MISSING_SPAN = "missing-span"
#: The span is empty, inverted, or entirely outside ``[0, totalSec]``.
REASON_EMPTY_SPAN = "empty-span"

#: The ops this module actually applies. Anything else is dropped with a reason.
SUPPORTED_OPS = ("delete", "trim")


class AddressedWord(TypedDict):
    """A §3 Word plus its stable address."""

    wordId: str
    segmentIndex: int
    wordIndex: int
    text: str
    start: float
    end: float


class TranscriptEditStats(TypedDict):
    """Per-category stats. The filler/silence fields mirror ``RefineStats``.

    ``wordsDeleted`` counts the edit spans that RESOLVED (a ``trim`` counts too,
    since it also removes speech) — NOT the rejected ones, and not the words the
    filler engine cut on its own (those stay in ``fillersRemoved``).
    """

    wordsDeleted: int
    deletedSec: float
    fillersRemoved: int
    fillerSeconds: float
    silenceRemovedSec: float
    keptSec: float
    removedSec: float


class TranscriptEditPlan(TypedDict):
    """The "see before you cut" plan: keep-list + stats + re-timed cues + drops."""

    keeps: list[list[float]]
    stats: TranscriptEditStats
    cues: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# T1 — stable word addressing (pure, non-mutating)
# --------------------------------------------------------------------------- #
def word_id(segment_index: int, word_index: int) -> str:
    """The stable address of a word: ``w{segmentIndex}-{wordIndex}``."""
    return f"w{segment_index}-{word_index}"


def _stamp(word: Mapping[str, Any], segment_index: int, word_index: int) -> dict[str, Any]:
    """Return a COPY of ``word`` carrying its address (an existing id wins)."""
    out = dict(word)
    out["wordId"] = str(out.get("wordId") or word_id(segment_index, word_index))
    out["segmentIndex"] = segment_index
    out["wordIndex"] = word_index
    return out


def address_transcript(transcript: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a COPY of ``transcript`` with a ``wordId`` stamped on every word.

    Never mutates the input (the immutability rule) and never raises on a
    malformed manifest: a non-mapping segment or word is passed through
    untouched, so an old project always round-trips.
    """
    if not transcript:
        return None
    out = dict(transcript)
    segments: list[Any] = []
    for seg_i, seg in enumerate(transcript.get("segments") or []):
        if not isinstance(seg, Mapping):
            segments.append(seg)
            continue
        new_seg = dict(seg)
        words = seg.get("words")
        if isinstance(words, Sequence) and not isinstance(words, str | bytes):
            new_seg["words"] = [
                _stamp(word, seg_i, w_i) if isinstance(word, Mapping) else word for w_i, word in enumerate(words)
            ]
        segments.append(new_seg)
    out["segments"] = segments
    return out


def addressed_words(transcript: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten every addressed word across segments, in transcript order."""
    addressed = address_transcript(transcript)
    if addressed is None:
        return []
    words: list[dict[str, Any]] = []
    for seg in addressed.get("segments") or []:
        if not isinstance(seg, Mapping):
            continue  # pragma: no cover - address_transcript preserves non-mappings verbatim
        for word in seg.get("words") or []:
            if isinstance(word, Mapping) and "wordId" in word:
                words.append(dict(word))
    return words


# --------------------------------------------------------------------------- #
# T3a — the pure EditSpan -> removed-span translator
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float | None:
    """Coerce a wire number, or ``None`` when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms_bounds(edit: Mapping[str, Any]) -> Span | None:
    """The explicit ``[startMs, endMs]`` bounds in seconds, when both are given."""
    start = _num(edit.get("startMs"))
    end = _num(edit.get("endMs"))
    if start is None or end is None:
        return None
    return (start / 1000.0, end / 1000.0)


def _word_bounds(edit: Mapping[str, Any], index: dict[str, Mapping[str, Any]]) -> tuple[Span | None, bool]:
    """Resolve a word address to its ``[start, end]``.

    Returns ``(span, addressed)`` — ``addressed`` is ``True`` when the edit DID
    name a word (so an unresolvable name is an ``unknown-word`` drop rather than
    a ``missing-span`` one).
    """
    wid = edit.get("wordId")
    if not isinstance(wid, str) or not wid:
        seg_i = edit.get("segmentIndex")
        w_i = edit.get("wordIndex")
        if not isinstance(seg_i, int) or not isinstance(w_i, int) or isinstance(seg_i, bool) or isinstance(w_i, bool):
            return None, False
        wid = word_id(seg_i, w_i)
    word = index.get(wid)
    if word is None:
        return None, True
    start = _num(word.get("start"))
    end = _num(word.get("end"))
    if start is None or end is None:
        return (0.0, 0.0), True  # junk timings -> an empty span, dropped below
    return (start, end), True


def resolve_edits(
    edits: Sequence[Any] | None,
    transcript: Mapping[str, Any] | None,
    total_sec: float,
) -> tuple[list[Span], list[dict[str, Any]]]:
    """Translate EditSpans into removed spans, dropping the impossible ones.

    Returns ``(removed_spans, rejected)`` in input order. NEVER raises — an
    unknown op, an unresolvable address, or a degenerate span is reported in
    ``rejected`` as ``{"index", "op", "reason"}`` (see the ``REASON_*``
    constants) so the UI can say exactly what it ignored.
    """
    total = max(0.0, float(total_sec))
    index = {word["wordId"]: word for word in addressed_words(transcript)}
    removed: list[Span] = []
    rejected: list[dict[str, Any]] = []

    def drop(i: int, op: str, reason: str) -> None:
        rejected.append({"index": i, "op": op, "reason": reason})

    for i, edit in enumerate(edits or []):
        if not isinstance(edit, Mapping):
            drop(i, "", REASON_UNKNOWN_OP)
            continue
        op = str(edit.get("op") or "delete")
        if op == "reorder":
            drop(i, op, REASON_REORDER_DEFERRED)
            continue
        if op not in SUPPORTED_OPS:
            drop(i, op, REASON_UNKNOWN_OP)
            continue

        span = _ms_bounds(edit)
        addressed = False
        if span is None and op == "delete":
            span, addressed = _word_bounds(edit, index)
        if span is None:
            drop(i, op, REASON_UNKNOWN_WORD if addressed else REASON_MISSING_SPAN)
            continue

        start = min(max(span[0], 0.0), total)
        end = min(max(span[1], 0.0), total)
        if end - start <= 1e-9:
            drop(i, op, REASON_EMPTY_SPAN)
            continue
        removed.append((start, end))
    return removed, rejected


# --------------------------------------------------------------------------- #
# T3b — compose the deletes with the SHIPPED filler/silence math
# --------------------------------------------------------------------------- #
def plan_transcript_edit(
    transcript: Mapping[str, Any] | None,
    edits: Sequence[Any] | None,
    total_sec: float,
    silences: Sequence[Span],
    *,
    remove_fillers: bool,
    remove_silence: bool,
    lang: str | None = None,
    merge_gap_ms: int = _fillers.DEFAULT_MERGE_GAP_MS,
    pad_sec: float = _silencetrim.DEFAULT_PAD_SEC,
    filler_sets: Mapping[str, Mapping[str, frozenset]] | None = None,
    cues: Sequence[Mapping[str, Any]] | None = None,
) -> TranscriptEditPlan:
    """Union the word edits with :func:`refine.plan_refine` into ONE keep-list.

    A word delete, a filler strip and a silence trim therefore render as a
    SINGLE ``build_segment_cut_argv`` pass (mirroring ``refine.apply``), and the
    removed regions are de-duplicated so an overlap is never double-counted.
    A delete that would remove the WHOLE clip degrades to a no-op keep-list
    (``build_segment_cut_argv`` requires at least one span).
    """
    total = max(0.0, float(total_sec))
    words = addressed_words(transcript)
    deleted, rejected = resolve_edits(edits, transcript, total)

    refine_plan = _refine.plan_refine(
        words,
        lang,
        total,
        silences,
        remove_fillers=remove_fillers,
        remove_silence=remove_silence,
        merge_gap_ms=merge_gap_ms,
        pad_sec=pad_sec,
        filler_sets=filler_sets,
    )
    refine_removed = _refine._removed_from_keeps(  # noqa: SLF001 - sibling module, same package
        [(a, b) for a, b in refine_plan["keeps"]], 0.0, total
    )

    deleted_union = _refine._union_spans(deleted)  # noqa: SLF001 - sibling module, same package
    deleted_sec = round(sum(b - a for a, b in deleted_union), 3)
    removed_union = _refine._union_spans([*deleted_union, *refine_removed])  # noqa: SLF001 - sibling module

    if total <= 0.0:
        keeps: list[list[float]] = []
    else:
        keeps = _refine._keeps_from_removed(removed_union, total) or [  # noqa: SLF001 - sibling module
            [0.0, round(total, 3)]
        ]
    kept_sec = round(sum(b - a for a, b in keeps), 3)

    return TranscriptEditPlan(
        keeps=keeps,
        stats=TranscriptEditStats(
            wordsDeleted=len(deleted),
            deletedSec=deleted_sec,
            fillersRemoved=refine_plan["stats"]["fillersRemoved"],
            fillerSeconds=refine_plan["stats"]["fillerSeconds"],
            silenceRemovedSec=refine_plan["stats"]["silenceRemovedSec"],
            keptSec=kept_sec,
            removedSec=round(total - kept_sec, 3),
        ),
        cues=_fillers.remap_cues(cues, [(a, b) for a, b in keeps]) if cues else [],
        rejected=rejected,
    )


# --------------------------------------------------------------------------- #
# small param helpers (mirror refine's coercion seams)
# --------------------------------------------------------------------------- #
def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _float(params: Mapping[str, Any], key: str, default: float) -> float:
    value = _num(params.get(key, default))
    return default if value is None else value


def _bool(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    return default if value is None else bool(value)


def _edit_history(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The project's edit ledger, tolerating a missing/corrupt value."""
    raw = project.get(EDITS_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(entry) for entry in raw if isinstance(entry, Mapping)]


# --------------------------------------------------------------------------- #
# T3c — the service (get/previewEdit = direct; applyEdit = job; undoEdit = direct)
# --------------------------------------------------------------------------- #
class TranscriptEditService:
    """Owns the four ``transcript.*`` methods over injectable seams.

    Seams are byte-identical to :class:`refine.RefineService` so the same fakes
    drive both. ``previewEdit`` never encodes and never writes; ``applyEdit``
    renders ONCE into ``out_dir`` (the source is never touched) and appends to
    the reversible edit ledger; ``undoEdit`` pops it back.
    """

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | os.PathLike[str],
        load_project: LoadProject,
        save_project: SaveProject,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
        detect_run: DetectRunner | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._load_project = load_project
        self._save_project = save_project
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._duration = duration
        self._detect_run = detect_run

    # ---- shared plumbing ---------------------------------------------------
    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, params: Mapping[str, Any]) -> str:
        path = params.get("path")
        if isinstance(path, str) and path:
            return path
        video_id = _require_str(params, "videoId")
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        return str(resolved)

    def _project(self, params: Mapping[str, Any]) -> dict[str, Any]:
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            return {}
        return dict(self._load_project(video_id) or {})

    def _plan(self, params: Mapping[str, Any], in_path: str, settings: dict[str, Any], total: float):
        """Detect silence + compose the plan (shared by previewEdit/applyEdit)."""
        silences = _silencetrim.detect_silence_spans(
            in_path,
            settings=settings,
            noise_db=_float(params, "noiseDb", _silencetrim.DEFAULT_NOISE_DB),
            min_silence_sec=_float(params, "minSilenceSec", _silencetrim.DEFAULT_MIN_SILENCE_SEC),
            run=self._detect_run,
        )
        return plan_transcript_edit(
            self._project(params).get("transcript"),
            params.get("edits"),
            total,
            silences,
            remove_fillers=_bool(params, "removeFillers", False),
            remove_silence=_bool(params, "removeSilence", False),
            lang=params.get("lang"),
            merge_gap_ms=int(_float(params, "mergeGapMs", float(_fillers.DEFAULT_MERGE_GAP_MS))),
            pad_sec=_float(params, "padSec", _silencetrim.DEFAULT_PAD_SEC),
            filler_sets=params.get("fillerSets"),
            cues=params.get("cues"),
        )

    # ---- transcript.get ----------------------------------------------------
    def get(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002 - RPC signature
        """``transcript.get({videoId})`` -> ``{transcript}`` with stamped ids.

        Returns ``{"transcript": None}`` when the project has not been
        transcribed yet — the renderer distinguishes "no transcript" from an
        empty one.
        """
        video_id = _require_str(params, "videoId")
        project = self._load_project(video_id) or {}
        return {"transcript": address_transcript(project.get("transcript"))}

    # ---- transcript.previewEdit -------------------------------------------
    def previewEdit(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002,N802 - wire name
        """``transcript.previewEdit({videoId|path, edits, ...})`` -> ``{plan}``.

        DIRECT: no encode, no file write — the "see before you cut" pass.
        """
        in_path = self._resolve(params)
        settings = self._settings()
        total = _float(params, "totalSec", 0.0)
        if total <= 0.0:
            total = _probe_total(self._duration, in_path, settings)
        return {"plan": self._plan(params, in_path, settings, total)}

    # ---- transcript.applyEdit ---------------------------------------------
    def applyEdit(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: N802 - wire name
        """``transcript.applyEdit({videoId|path, edits, ...})`` -> ``{jobId}``.

        ``job.done.result`` = ``{path, removedSec, stats, plan, editId, cues?}``.
        Renders ONCE via :func:`fillers.build_segment_cut_argv` into
        ``out_dir/{stem}.edited.mp4`` — the source file is NEVER touched — then
        appends ``{editId, path, sourcePath, removedSec, keeps}`` to the
        project's ledger so :meth:`undoEdit` can walk it back. When nothing is
        removed the original path passes straight through (no encode, no
        ledger entry, ``editId=None``).
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        settings = self._settings()
        run = self._run if self._run is not None else _default_run()
        duration = self._duration
        out_dir = self._out_dir
        video_id = params.get("videoId")
        plan_params = dict(params)

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            job_ctx.progress(5, "planning transcript edit")
            total = _probe_total(duration, in_path, settings)
            if total <= 0.0:
                job_ctx.progress(100, "nothing to edit")
                return _passthrough(in_path, _empty_plan(0.0))
            plan = self._plan(plan_params, in_path, settings, total)
            keeps = [(float(a), float(b)) for a, b in plan["keeps"]]
            removed = plan["stats"]["removedSec"]
            if removed <= 1e-3 or len(keeps) <= 1:
                job_ctx.progress(100, "nothing to edit")
                return _passthrough(in_path, plan)
            job_ctx.raise_if_cancelled()
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(in_path).stem or "clip"
            out_path = str(out_dir / f"{stem}.edited.mp4")
            argv = _fillers.build_segment_cut_argv(in_path, out_path, keeps, settings)
            job_ctx.progress(40, "re-cutting")
            code = run(argv, total_sec=total)
            if code != 0:
                raise RpcError(f"transcript edit re-cut failed (ffmpeg exit {code})", ErrorCode.INTERNAL_ERROR)
            edit_id = self._record(video_id, out_path, in_path, removed, plan["keeps"])
            result: dict[str, Any] = {
                "path": out_path,
                "removedSec": removed,
                "stats": plan["stats"],
                "plan": plan,
                "editId": edit_id,
            }
            if plan["cues"]:
                result["cues"] = plan["cues"]
            job_ctx.progress(100, f"removed {removed:.1f}s")
            return result

        job = ctx.jobs.start(job_body, feature="transcriptEdit", label="transcript edit", videoId=video_id)
        return {"jobId": job.id}

    def _record(
        self,
        video_id: Any,
        out_path: str,
        source_path: str,
        removed: float,
        keeps: list[list[float]],
    ) -> str | None:
        """Append the edit to the project ledger; returns its deterministic id."""
        if not isinstance(video_id, str) or not video_id:
            return None
        project = dict(self._load_project(video_id) or {})
        history = _edit_history(project)
        edit_id = f"tedit-{len(history) + 1}"
        history.append(
            {
                "editId": edit_id,
                "path": out_path,
                "sourcePath": source_path,
                "removedSec": removed,
                "keeps": keeps,
            }
        )
        project[EDITS_KEY] = history
        self._save_project(video_id, project)
        return edit_id

    # ---- transcript.undoEdit ----------------------------------------------
    def undoEdit(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002,N802 - wire name
        """``transcript.undoEdit({videoId, editId?})`` -> ``{editId, path, undone}``.

        Pops the newest ledger entry (or asserts it is ``editId``) and returns
        the path that becomes current again — the previous edit's output, or the
        untouched original. The rendered file is left on disk (it is a sibling,
        never the source), so an undo is cheap and re-doable by re-applying.
        """
        video_id = _require_str(params, "videoId")
        project = dict(self._load_project(video_id) or {})
        history = _edit_history(project)
        if not history:
            raise _invalid("nothing to undo for this video")
        wanted = params.get("editId")
        if isinstance(wanted, str) and wanted and wanted != history[-1]["editId"]:
            raise _invalid(f"cannot undo {wanted}: the newest edit is {history[-1]['editId']}")
        undone = history.pop()
        project[EDITS_KEY] = history
        self._save_project(video_id, project)
        return {
            "editId": undone["editId"],
            "path": history[-1]["path"] if history else undone["sourcePath"],
            "undone": undone,
        }


# --------------------------------------------------------------------------- #
# module helpers
# --------------------------------------------------------------------------- #
def _default_run() -> RunFn:
    """The real drained ffmpeg ``run`` seam (lazy import keeps the module light)."""
    from .. import ffmpeg as _ffmpeg  # noqa: PLC0415 - lazy: avoids an import cycle

    return _ffmpeg.run


def _default_duration() -> ProbeFn:
    """The real ffprobe duration seam (lazy import keeps the module light)."""
    from .. import ffmpeg as _ffmpeg  # noqa: PLC0415 - lazy: avoids an import cycle

    return _ffmpeg.ffprobe_duration


def _probe_total(duration: ProbeFn | None, in_path: str, settings: dict[str, Any]) -> float:
    """Probe the clip duration through the seam; a probe failure -> 0.0."""
    probe = duration if duration is not None else _default_duration()
    try:
        return float(probe(in_path, settings))
    except Exception:  # noqa: BLE001 - a probe failure means we can't cut safely
        log.warning("duration probe failed for %s; skipping transcript edit", in_path)
        return 0.0


def _empty_plan(total: float) -> TranscriptEditPlan:
    return TranscriptEditPlan(
        keeps=[] if total <= 0.0 else [[0.0, round(total, 3)]],
        stats=TranscriptEditStats(
            wordsDeleted=0,
            deletedSec=0.0,
            fillersRemoved=0,
            fillerSeconds=0.0,
            silenceRemovedSec=0.0,
            keptSec=round(total, 3),
            removedSec=0.0,
        ),
        cues=[],
        rejected=[],
    )


def _passthrough(in_path: str, plan: TranscriptEditPlan) -> dict[str, Any]:
    """The no-encode result: the ORIGINAL path, nothing removed, nothing recorded."""
    return {"path": in_path, "removedSec": 0.0, "stats": plan["stats"], "plan": plan, "editId": None}


# --------------------------------------------------------------------------- #
# registration (called from handlers.register_all — the ONE RPC site)
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    out_dir: str | os.PathLike[str],
    load_project: LoadProject,
    save_project: SaveProject,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    detect_run: DetectRunner | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> TranscriptEditService:
    """Create the service and register the four ``transcript.*`` methods.

    Mirrors :func:`refine.register`: ``register_fn`` defaults to
    :func:`protocol.register` (duplicates fail loudly); tests inject a fake
    registrar + fake seams. ``get``/``previewEdit``/``undoEdit`` are DIRECT
    handlers; ``applyEdit`` runs as a job.
    """
    service = TranscriptEditService(
        resolver=resolver,
        out_dir=out_dir,
        load_project=load_project,
        save_project=save_project,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
        detect_run=detect_run,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("transcript.get", service.get)
    reg("transcript.previewEdit", service.previewEdit)
    reg("transcript.applyEdit", service.applyEdit)
    reg("transcript.undoEdit", service.undoEdit)
    log.info("registered transcript.get + previewEdit + applyEdit + undoEdit")
    return service


__all__ = [
    "EDITS_KEY",
    "REASON_EMPTY_SPAN",
    "REASON_MISSING_SPAN",
    "REASON_REORDER_DEFERRED",
    "REASON_UNKNOWN_OP",
    "REASON_UNKNOWN_WORD",
    "SUPPORTED_OPS",
    "AddressedWord",
    "TranscriptEditPlan",
    "TranscriptEditService",
    "TranscriptEditStats",
    "address_transcript",
    "addressed_words",
    "plan_transcript_edit",
    "register",
    "resolve_edits",
    "word_id",
]
