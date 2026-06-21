"""REFINE — pure span/stat unifier for filler + silence removal (WU-1).

``plan_refine`` composes the ALREADY-SHIPPED, already-tested timeline math —
filler cut-lists (:func:`features.fillers.build_cutlist_with_stats`) and silence
keep-spans (:func:`features.silencetrim.keep_spans`) — into ONE union keep-list
plus mirrored stats. It is a Descript-style "see before you cut" planner:

    plan_refine(words, lang, total_sec, silences, *,
                remove_fillers, remove_silence,
                merge_gap_ms=..., pad_sec=..., filler_sets=None) -> RefinePlan

with ``RefinePlan = {"keeps": [[s, e], ...], "stats": {...}}``.

NO subprocess, NO model, NO I/O. The two engines each emit KEEP spans; the
removed regions are the gaps inside their respective windows. Combining a
filler-removal AND a silence-removal means the FINAL removed region is the
*union* of the two removed sets (so a filler that sits inside a silence is one
removed region, not two — no double-count). The final keep-list is therefore
``[0, total_sec]`` minus that union. Per-category stats stay independent
(``fillersRemoved``/``fillerSeconds`` mirror the shipped per-clip stats and
``silenceRemovedSec`` mirrors :func:`silencetrim.removed_seconds`), while
``keptSec`` reflects the de-duplicated union so it always equals
``total_sec - |union of removed|``.
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
from . import silencetrim as _silencetrim

log = get_logger("media_studio.refine")

# Injectable seams (mirror the sibling features — silencetrim / diarize).
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
DetectRunner = Callable[..., Any]
Resolver = Callable[[str], str | None]
LoadProject = Callable[[str], dict[str, Any]]
SaveProject = Callable[[str, dict[str, Any]], None]

# A keep span as emitted in the plan: [start, end] in original-video seconds.
Span = tuple[float, float]


class RefineStats(TypedDict):
    """Per-category refine stats (mirrors the shipped per-clip stat fields)."""

    fillersRemoved: int
    fillerSeconds: float
    silenceRemovedSec: float
    keptSec: float


class RefinePlan(TypedDict):
    """The pure refine plan: a union keep-list plus de-duplicated stats."""

    keeps: list[list[float]]
    stats: RefineStats


def _removed_from_keeps(keeps: Sequence[Span], lo: float, hi: float) -> list[Span]:
    """Invert ``keeps`` into the removed regions across ``[lo, hi]``.

    Every part of ``[lo, hi]`` not covered by a keep is a removed region (head,
    interior gaps, and tail all count). An empty keep-list means the engine
    declined to cut anything (it leaves the span whole), so nothing is removed.
    Callers pass ``[lo, hi]`` = the engine's removal window: ``[0, total]`` for
    silence (edge silences count) and the words' own span for fillers (nothing
    outside the transcript is ever a filler cut).
    """
    if hi <= lo or not keeps:
        return []
    spans = sorted((max(lo, float(a)), min(hi, float(b))) for a, b in keeps if float(b) > float(a))
    removed: list[Span] = []
    cursor = lo
    for start, end in spans:
        if start > cursor:
            removed.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        removed.append((cursor, hi))
    return removed


def _union_spans(spans: Sequence[Span]) -> list[Span]:
    """Merge overlapping/adjacent spans into a minimal sorted union."""
    ordered = sorted((float(a), float(b)) for a, b in spans if float(b) > float(a))
    merged: list[Span] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end))
        else:
            merged.append((start, end))
    return merged


def _keeps_from_removed(removed: Sequence[Span], total: float) -> list[list[float]]:
    """Invert the (already-unioned) removed regions over ``[0, total]``."""
    keeps: list[list[float]] = []
    cursor = 0.0
    for start, end in removed:
        if start > cursor:
            keeps.append([round(cursor, 3), round(start, 3)])
        cursor = max(cursor, end)
    if cursor < total:
        keeps.append([round(cursor, 3), round(total, 3)])
    return keeps


def plan_refine(
    words: Sequence[Mapping[str, Any]],
    lang: str | None,
    total_sec: float,
    silences: Sequence[Span],
    *,
    remove_fillers: bool,
    remove_silence: bool,
    merge_gap_ms: int = _fillers.DEFAULT_MERGE_GAP_MS,
    pad_sec: float = _silencetrim.DEFAULT_PAD_SEC,
    filler_sets: Mapping[str, Mapping[str, frozenset]] | None = None,
) -> RefinePlan:
    """Compose filler + silence removal into ONE union keep-list and stats.

    ``words`` are §3 Words (original-video seconds), ``silences`` are detected
    silent spans, ``total_sec`` the clip duration. ``filler_sets`` (default
    ``None`` ⇒ :data:`fillers.DEFAULT_SETS`) is threaded straight into the
    filler engine's ``fillers=`` kwarg, so a caller-supplied per-language
    override genuinely changes which words are cut.
    """
    total = max(0.0, float(total_sec))

    filler_seconds = 0.0
    fillers_removed = 0
    filler_removed: list[Span] = []
    if remove_fillers:
        sets = filler_sets if filler_sets is not None else _fillers.DEFAULT_SETS
        keeps, stats = _fillers.build_cutlist_with_stats(
            words,
            lang,
            fillers=sets,
            merge_gap_ms=merge_gap_ms,
        )
        filler_seconds = float(stats["fillerSeconds"])
        fillers_removed = int(stats["fillersRemoved"])
        win_lo = keeps[0][0] if keeps else 0.0
        win_hi = keeps[-1][1] if keeps else 0.0
        filler_removed = _removed_from_keeps(keeps, win_lo, win_hi)

    silence_removed_sec = 0.0
    silence_removed: list[Span] = []
    if remove_silence:
        keeps = _silencetrim.keep_spans(silences, total, pad_sec=pad_sec)
        silence_removed_sec = _silencetrim.removed_seconds(keeps, total)
        silence_removed = _removed_from_keeps(keeps, 0.0, total)

    removed = _union_spans([*filler_removed, *silence_removed])
    if total <= 0.0:
        keeps_out: list[list[float]] = []
    else:
        keeps_out = _keeps_from_removed(removed, total) or [[0.0, round(total, 3)]]

    kept_sec = round(sum(b - a for a, b in keeps_out), 3)

    return RefinePlan(
        keeps=keeps_out,
        stats=RefineStats(
            fillersRemoved=fillers_removed,
            fillerSeconds=round(filler_seconds, 3),
            silenceRemovedSec=round(silence_removed_sec, 3),
            keptSec=kept_sec,
        ),
    )


# --------------------------------------------------------------------------- #
# small param helpers (mirror silencetrim's coercion seams)
# --------------------------------------------------------------------------- #
def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _float(params: Mapping[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    return default if value is None else bool(value)


def _words_of(transcript: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten a transcript's per-segment word timings into the flat §3 list.

    Mirrors :func:`shortmaker._words_of` — the one canonical transcript→words
    flattening the planner expects. A missing transcript / segments / words all
    collapse to an empty list (the planner then plans on silence alone).
    """
    words: list[dict[str, Any]] = []
    if not transcript:
        return words
    for seg in transcript.get("segments", []) or []:
        for word in (seg or {}).get("words") or []:
            words.append(word)
    return words


# --------------------------------------------------------------------------- #
# the service (refine.preview = direct / no encode; refine.apply = a job)
# --------------------------------------------------------------------------- #
class RefineService:
    """Owns ``refine.preview`` + ``refine.apply`` over injectable seams.

    Seams mirror :class:`silencetrim.SilenceTrim` (``resolver``, ``out_dir``,
    ``settings_provider``, ``run``, ``duration``, ``detect_run``) PLUS the two
    project-store seams the diarize feature already exposes
    (``load_project`` / ``save_project``) so the transcript words are read
    through a fake in tests — never real I/O in the service body. ``preview``
    is a Descript-style "see before you cut" planner (detect + plan, NO encode,
    NO write); ``apply`` re-cuts as a job (writing a NEW ``*.refined.mp4`` so the
    original is untouched) and re-times caption cues via
    :func:`fillers.remap_cues`.
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

    def _words(self, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Load the project's transcript words via the ``load_project`` seam."""
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            return []
        project = self._load_project(video_id) or {}
        return _words_of(project.get("transcript"))

    def _plan(self, params: Mapping[str, Any], in_path: str, settings: dict[str, Any], total: float) -> RefinePlan:
        """Detect silence + compose the pure refine plan (shared by preview/apply)."""
        silences = _silencetrim.detect_silence_spans(
            in_path,
            settings=settings,
            noise_db=_float(params, "noiseDb", _silencetrim.DEFAULT_NOISE_DB),
            min_silence_sec=_float(params, "minSilenceSec", _silencetrim.DEFAULT_MIN_SILENCE_SEC),
            run=self._detect_run,
        )
        return plan_refine(
            self._words(params),
            params.get("lang"),
            total,
            silences,
            remove_fillers=_bool(params, "removeFillers", True),
            remove_silence=_bool(params, "removeSilence", True),
            merge_gap_ms=int(_float(params, "mergeGapMs", float(_fillers.DEFAULT_MERGE_GAP_MS))),
            pad_sec=_float(params, "padSec", _silencetrim.DEFAULT_PAD_SEC),
            filler_sets=params.get("fillerSets"),
        )

    def preview(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:  # noqa: ARG002 - RPC signature
        """``refine.preview({videoId|path, removeFillers?, removeSilence?, ...})``.

        Resolves the clip, detects silence (the ``detect_run`` seam), reads the
        transcript words (``load_project`` seam), and returns the pure
        :func:`plan_refine` result as ``{plan}``. NO encode, NO file write —
        the user sees the proposed cut before committing.
        """
        in_path = self._resolve(params)
        settings = self._settings()
        total = _float(params, "totalSec", 0.0)
        if total <= 0.0:
            total = _probe_total(self._duration, in_path, settings)
        return {"plan": self._plan(params, in_path, settings, total)}

    def apply(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``refine.apply({videoId|path, ...})`` -> ``{jobId}`` -> the cut result.

        ``job.done.result`` = ``{path, removedSec, stats, plan, cues?}``. Builds
        the keep-list via :func:`plan_refine`, re-cuts through the injected
        ``run`` seam (writing ``out_dir/{stem}.refined.mp4`` — the original is
        never touched), and re-times any caller-supplied ``cues`` via
        :func:`fillers.remap_cues`. When there is nothing to cut the original
        path is returned unchanged with ``removedSec == 0`` (no re-encode).
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        settings = self._settings()
        run = self._run if self._run is not None else _default_run()
        duration = self._duration
        out_dir = self._out_dir
        cues = params.get("cues")
        plan_params = dict(params)

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            job_ctx.progress(5, "planning refine")
            total = _probe_total(duration, in_path, settings)
            if total <= 0.0:
                job_ctx.progress(100, "nothing to refine")
                return {"path": in_path, "removedSec": 0.0, "stats": _zero_stats(), "plan": _passthrough_plan(total)}
            plan = self._plan(plan_params, in_path, settings, total)
            keeps = [(float(a), float(b)) for a, b in plan["keeps"]]
            removed = round(total - plan["stats"]["keptSec"], 3)
            # Nothing to remove (single full-length keep): pass through untouched.
            if removed <= 1e-3 or len(keeps) <= 1:
                job_ctx.progress(100, "nothing to refine")
                return {"path": in_path, "removedSec": 0.0, "stats": plan["stats"], "plan": plan}
            job_ctx.raise_if_cancelled()
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(in_path).stem or "clip"
            out_path = str(out_dir / f"{stem}.refined.mp4")
            argv = _fillers.build_segment_cut_argv(in_path, out_path, keeps, settings)
            job_ctx.progress(40, "re-cutting")
            code = run(argv, total_sec=total)
            if code != 0:
                raise RpcError(f"refine re-cut failed (ffmpeg exit {code})", ErrorCode.INTERNAL_ERROR)
            result: dict[str, Any] = {
                "path": out_path,
                "removedSec": removed,
                "stats": plan["stats"],
                "plan": plan,
            }
            if cues is not None:
                result["cues"] = _fillers.remap_cues(cues, keeps)
            job_ctx.progress(100, f"removed {removed:.1f}s")
            return result

        job = ctx.jobs.start(job_body, feature="refine", label="refine", videoId=params.get("videoId"))
        return {"jobId": job.id}


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
    except Exception:  # noqa: BLE001 - a probe failure means we can't refine safely
        log.warning("duration probe failed for %s; skipping refine", in_path)
        return 0.0


def _zero_stats() -> RefineStats:
    return RefineStats(fillersRemoved=0, fillerSeconds=0.0, silenceRemovedSec=0.0, keptSec=0.0)


def _passthrough_plan(total: float) -> RefinePlan:
    return RefinePlan(keeps=[] if total <= 0.0 else [[0.0, round(total, 3)]], stats=_zero_stats())


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
) -> RefineService:
    """Create the service and register ``refine.preview`` + ``refine.apply``.

    Mirrors :func:`silencetrim.register`: ``register_fn`` defaults to
    :func:`protocol.register` (duplicates fail loudly); tests inject a fake
    registrar + fake seams. ``refine.preview`` is a DIRECT handler (no job);
    ``refine.apply`` runs as a job. Returns the service for the caller to hold.
    """
    service = RefineService(
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
    reg("refine.preview", service.preview)
    reg("refine.apply", service.apply)
    log.info("registered refine.preview + refine.apply")
    return service


__all__ = [
    "RefinePlan",
    "RefineService",
    "RefineStats",
    "plan_refine",
    "register",
]
