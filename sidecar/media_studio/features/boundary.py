"""Deterministic boundary-snapping for short-maker candidates.

The LLM selection pass (``select.py`` / ``spike/select.py``) returns rough
``[Candidate]`` clips. This module snaps each candidate's ``start``/``end`` to the
nearest *valid* boundary so cuts land cleanly:

* **sentence end** — derived from word timings (a word whose text ends in a
  sentence-terminal punctuation mark; the boundary is that word's ``end``),
* **audio silence** — midpoints of detected silent gaps,
* **scene cut** — detected scene-change timestamps.

Every snapped clip must stay within the 20-60s window (§5), must never cut
mid-word, and the operation must be **idempotent** (snapping an already-snapped
clip returns the same clip). A candidate with no valid boundary set that keeps it
in range is **dropped with a reason** rather than silently mangled.

Detection of silence / scene cuts lives behind a *seam*: this module never runs
ffmpeg or PySceneDetect itself. The orchestrator injects concrete lists (or
provider callables) produced by ``ffmpeg silencedetect`` / PySceneDetect; the
tests inject known lists. See CONTRACTS.md §3 (Candidate) and §5 (recipe).

Pure-logic, dependency-free (stdlib + util only) — no heavy-ML imports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.boundary")

# --- Tunables (§5: each clip 20-60s, hard) ----------------------------------
MIN_SEC: float = 20.0
MAX_SEC: float = 60.0

# N1 (V1.1 SEL1) — "mid-form" relaxes the hard snap window so a long moment can be
# kept WHOLE instead of being trimmed back to 60 s. The verified OpusClip teardown
# (docs/research/OPUSCLIP-PARITY-IMPROVEMENT-NOTE) shows real clips run 16-160 s,
# NOT 60-capped. The envelope per mode is the single source of truth shared with
# ``select.py`` (the two modules must agree so a select-side mid-form candidate is
# not silently clamped at the boundary stage).
MIDFORM_MIN_SEC: float = 16.0
MIDFORM_MAX_SEC: float = 180.0
DEFAULT_DURATION_MODE: str = "standard"
_DURATION_ENVELOPES: dict[str, tuple[float, float]] = {
    "standard": (MIN_SEC, MAX_SEC),
    "midform": (MIDFORM_MIN_SEC, MIDFORM_MAX_SEC),
}


def resolve_window(mode: Any) -> tuple[float, float]:
    """Return the hard ``(min_sec, max_sec)`` snap window for a duration mode.

    ``"standard"`` is the frozen 20-60 s window; ``"midform"`` relaxes it to
    16-180 s. An unknown / non-string mode fails **closed** to ``"standard"``
    (mirrors the select-side GATE-2 out-of-enum clamp) — never silently widening
    the window on a typo.
    """
    if isinstance(mode, str) and mode in _DURATION_ENVELOPES:
        return _DURATION_ENVELOPES[mode]
    return _DURATION_ENVELOPES[DEFAULT_DURATION_MODE]


# Characters that, when a word's text ends with one of them, mark a complete
# sentence/thought — the snap target is that word's ``end`` time.
_SENTENCE_TERMINATORS: tuple[str, ...] = (".", "!", "?", "…")
# Trailing characters stripped before checking for a terminator (quotes/brackets
# commonly trail terminal punctuation, e.g. ``done."`` or ``done.)``).
_TRAILING_TRIM: str = "\"'’”»)]}"

# Floating-point comparison tolerance (seconds). Word/silence/scene times come
# from ffprobe/whisper at ms-ish resolution; treat sub-ms diffs as equal so
# idempotence holds across repeated snaps.
EPS: float = 1e-6


# --- Types ------------------------------------------------------------------
# A Word per §3: {text, start, end}. We accept any mapping with those keys.
Word = dict[str, Any]
# A Candidate per §3: {rank, start, end, durationSec, hook, why, score, sourceStart}.
Candidate = dict[str, Any]

# Seam providers: the orchestrator supplies these (filled by ffmpeg / PySceneDetect).
# Both take no arguments here because detection is per-video; the orchestrator
# binds the video path before passing them in. Each returns a sorted-or-unsorted
# list of timestamps (seconds).
SilenceProvider = Callable[[], Sequence[float]]
SceneProvider = Callable[[], Sequence[float]]


@dataclass(frozen=True)
class BoundarySet:
    """The valid snap targets for one video, in seconds.

    ``sentence_ends`` are word-derived complete-thought boundaries. ``silences``
    are silence-gap midpoints. ``scene_cuts`` are scene-change timestamps. All
    are candidate snap targets; the snapper picks the nearest one that keeps the
    clip in range and word-aligned.
    """

    sentence_ends: tuple[float, ...] = ()
    silences: tuple[float, ...] = ()
    scene_cuts: tuple[float, ...] = ()

    def all_targets(self) -> tuple[float, ...]:
        """Every snap target, de-duplicated and sorted ascending."""
        merged = set(self.sentence_ends) | set(self.silences) | set(self.scene_cuts)
        return tuple(sorted(merged))


@dataclass(frozen=True)
class SnapResult:
    """Outcome of snapping a single candidate.

    Exactly one of ``candidate`` / ``dropped`` is meaningful: a kept clip carries
    the re-snapped ``candidate`` (``dropped is False``); a dropped clip carries
    ``dropped=True`` and a human-readable ``reason``.
    """

    candidate: Candidate | None
    dropped: bool = False
    reason: str = ""

    @property
    def kept(self) -> bool:
        """True if the candidate survived snapping (was not dropped)."""
        return not self.dropped


# --- Word-boundary helpers --------------------------------------------------
def _ends_sentence(text: str) -> bool:
    """True if ``text`` (a word) ends a sentence/complete thought.

    Trailing quotes/brackets are trimmed first so ``done."`` still counts.
    """
    trimmed = text.rstrip(_TRAILING_TRIM).rstrip()
    return trimmed.endswith(_SENTENCE_TERMINATORS)


def sentence_ends_from_words(words: Sequence[Word]) -> tuple[float, ...]:
    """Derive sentence-end boundary times from word timings.

    A boundary is the ``end`` time of any word whose text ends with sentence
    punctuation. Words missing ``text``/``end`` are skipped (defensive — whisper
    output is trusted but not assumed complete). Returned sorted ascending,
    de-duplicated.
    """
    ends: set[float] = set()
    for w in words:
        text = w.get("text")
        end = w.get("end")
        if not isinstance(text, str) or not isinstance(end, (int, float)):
            continue
        if _ends_sentence(text):
            ends.add(float(end))
    return tuple(sorted(ends))


def _word_spans(words: Sequence[Word]) -> tuple[tuple[float, float], ...]:
    """Return sorted ``(start, end)`` spans for words that carry valid timings."""
    spans: list[tuple[float, float]] = []
    for w in words:
        start = w.get("start")
        end = w.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            spans.append((float(start), float(end)))
    spans.sort()
    return tuple(spans)


def _cuts_mid_word(t: float, spans: Sequence[tuple[float, float]]) -> bool:
    """True if time ``t`` falls strictly inside any word span (mid-word).

    A cut exactly at a word's ``start`` or ``end`` is on a word boundary and is
    fine; only a time strictly between a word's start and end mid-word.
    """
    return any(start + EPS < t < end - EPS for start, end in spans)


# --- Snap-target selection --------------------------------------------------
def _nearest_valid(
    original: float,
    targets: Sequence[float],
    *,
    lower: float,
    upper: float,
    spans: Sequence[tuple[float, float]],
) -> float | None:
    """Pick the snap target nearest ``original`` within ``[lower, upper]``.

    Targets that fall outside the inclusive ``[lower, upper]`` window or that
    would cut mid-word are rejected. Ties (equal distance) break toward the
    *smaller* timestamp for determinism. Returns ``None`` if no target qualifies.
    """
    best: float | None = None
    best_dist: float | None = None
    for t in targets:
        if t < lower - EPS or t > upper + EPS:
            continue
        if _cuts_mid_word(t, spans):
            continue
        dist = abs(t - original)
        if best_dist is None or dist < best_dist - EPS:
            best, best_dist = t, dist
        elif abs(dist - best_dist) <= EPS and (best is None or t < best):
            best = t
    return best


# --- Public API -------------------------------------------------------------
def build_boundary_set(
    words: Sequence[Word],
    *,
    silences: Sequence[float] | None = None,
    scene_cuts: Sequence[float] | None = None,
    silence_provider: SilenceProvider | None = None,
    scene_provider: SceneProvider | None = None,
) -> BoundarySet:
    """Assemble a :class:`BoundarySet` from words + injected silence/scene lists.

    The silence/scene lists may be passed directly (tests inject known lists) or
    pulled from seam *providers* the orchestrator binds to ffmpeg / PySceneDetect.
    Direct lists take precedence over providers when both are given. Sentence
    ends are always derived from ``words``.
    """
    if silences is None and silence_provider is not None:
        silences = silence_provider()
    if scene_cuts is None and scene_provider is not None:
        scene_cuts = scene_provider()

    def _clean(values: Sequence[float] | None) -> tuple[float, ...]:
        if not values:
            return ()
        return tuple(sorted({float(v) for v in values if isinstance(v, (int, float))}))

    return BoundarySet(
        sentence_ends=sentence_ends_from_words(words),
        silences=_clean(silences),
        scene_cuts=_clean(scene_cuts),
    )


def snap_candidate(
    candidate: Candidate,
    words: Sequence[Word],
    boundaries: BoundarySet,
    *,
    min_sec: float = MIN_SEC,
    max_sec: float = MAX_SEC,
) -> SnapResult:
    """Snap one candidate's start/end to valid boundaries, or drop it.

    Strategy (deterministic):

    1. Snap ``start`` to the nearest valid target near the original start, then
       snap ``end`` to the nearest valid target that keeps the resulting duration
       in ``[min_sec, max_sec]`` and that is not mid-word.
    2. If no qualifying ``end`` exists, retry: keep the original ``end`` and snap
       ``start`` to satisfy the window (covers clips already ending on a boundary).
    3. If neither yields an in-range, word-aligned, non-empty clip, drop with a
       reason.

    The returned candidate preserves all non-geometry fields (rank/hook/why/
    score/sourceStart) and recomputes ``durationSec``. Idempotent: re-snapping a
    clip already on boundaries returns an equivalent clip.
    """
    try:
        orig_start = float(candidate["start"])
        orig_end = float(candidate["end"])
    except (KeyError, TypeError, ValueError) as exc:
        return SnapResult(candidate=None, dropped=True, reason=f"invalid start/end: {exc}")

    if orig_end <= orig_start:
        return SnapResult(
            candidate=None,
            dropped=True,
            reason=f"non-positive duration ({orig_start:.3f}..{orig_end:.3f})",
        )

    if min_sec > max_sec:
        raise ValueError(f"min_sec ({min_sec}) must be <= max_sec ({max_sec})")

    spans = _word_spans(words)
    targets = boundaries.all_targets()

    snapped = _snap_pair(orig_start, orig_end, targets, spans, min_sec=min_sec, max_sec=max_sec)
    if snapped is None:
        return SnapResult(
            candidate=None,
            dropped=True,
            reason=(f"no valid boundary keeps the clip within {min_sec:g}-{max_sec:g}s without cutting mid-word"),
        )

    new_start, new_end = snapped
    out = dict(candidate)
    out["start"] = new_start
    out["end"] = new_end
    out["durationSec"] = round(new_end - new_start, 3)
    return SnapResult(candidate=out, dropped=False)


def _snap_pair(
    orig_start: float,
    orig_end: float,
    targets: Sequence[float],
    spans: Sequence[tuple[float, float]],
    *,
    min_sec: float,
    max_sec: float,
) -> tuple[float, float] | None:
    """Return an in-range, word-aligned ``(start, end)`` pair, or ``None``.

    Tries start-first then end-first so a clip whose original start *or* end
    already sits on a boundary still snaps. Among valid pairs, prefers the one
    closest (summed distance) to the original endpoints, breaking ties toward the
    earlier start then earlier end for determinism.
    """
    candidates: list[tuple[float, float]] = []

    # Pass A: snap start first, then derive a window for end.
    start_a = _nearest_valid(orig_start, targets, lower=0.0, upper=orig_end, spans=spans)
    if start_a is not None:
        end_a = _nearest_valid(
            orig_end,
            targets,
            lower=start_a + min_sec,
            upper=start_a + max_sec,
            spans=spans,
        )
        if end_a is not None and end_a > start_a + EPS:
            candidates.append((start_a, end_a))

    # Pass B: snap end first, then derive a window for start.
    end_b = _nearest_valid(orig_end, targets, lower=orig_start, upper=_upper_bound(targets, orig_end), spans=spans)
    if end_b is not None:
        start_b = _nearest_valid(
            orig_start,
            targets,
            lower=max(0.0, end_b - max_sec),
            upper=end_b - min_sec,
            spans=spans,
        )
        if start_b is not None and end_b > start_b + EPS:
            candidates.append((start_b, end_b))

    if not candidates:
        return None

    def _cost(pair: tuple[float, float]) -> tuple[float, float, float]:
        s, e = pair
        return (abs(s - orig_start) + abs(e - orig_end), s, e)

    return min(candidates, key=_cost)


def _upper_bound(targets: Sequence[float], orig_end: float) -> float:
    """Upper search bound for the end snap: the largest target >= orig_end.

    Lets the end snap *extend* past the original (e.g. to reach a sentence end a
    few seconds later) while staying anchored to real boundaries. Falls back to
    ``orig_end`` if no target reaches that far.
    """
    reachable = [t for t in targets if t >= orig_end - EPS]
    return max(reachable) if reachable else orig_end


def snap_candidates(
    candidates: Sequence[Candidate],
    words: Sequence[Word],
    boundaries: BoundarySet,
    *,
    min_sec: float = MIN_SEC,
    max_sec: float = MAX_SEC,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Snap a batch of candidates; return ``(kept, dropped)``.

    ``kept`` is the list of re-snapped candidates (geometry updated, other fields
    preserved), re-ranked 1..N in their original order. ``dropped`` is a list of
    ``{candidate, reason}`` for every candidate with no valid boundary.

    Idempotent at the batch level: feeding the kept list back through (with the
    same boundaries that now include the snapped endpoints) yields the same
    geometry.
    """
    kept: list[Candidate] = []
    dropped: list[dict[str, Any]] = []
    for cand in candidates:
        result = snap_candidate(cand, words, boundaries, min_sec=min_sec, max_sec=max_sec)
        if result.dropped or result.candidate is None:
            dropped.append({"candidate": cand, "reason": result.reason})
            log.info(
                "boundary: dropped candidate rank=%s start=%s end=%s reason=%s",
                cand.get("rank"),
                cand.get("start"),
                cand.get("end"),
                result.reason,
            )
        else:
            kept.append(result.candidate)

    # Re-rank kept clips 1..N preserving input order (rank is presentation order).
    for i, cand in enumerate(kept, start=1):
        cand["rank"] = i
    return kept, dropped


def snap_from_lists(
    candidates: Sequence[Candidate],
    words: Sequence[Word],
    *,
    silences: Sequence[float] | None = None,
    scene_cuts: Sequence[float] | None = None,
    silence_provider: SilenceProvider | None = None,
    scene_provider: SceneProvider | None = None,
    min_sec: float = MIN_SEC,
    max_sec: float = MAX_SEC,
    duration_mode: str | None = None,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Convenience: build the boundary set then snap a batch in one call.

    This is the orchestrator-facing entry point. The orchestrator passes the
    detected silence/scene lists (or seam providers bound to ffmpeg /
    PySceneDetect); tests pass known lists directly.

    ``duration_mode`` (N1, V1.1 SEL1), when supplied, resolves the hard
    ``(min_sec, max_sec)`` snap window via :func:`resolve_window` — so a
    ``"midform"`` request keeps a 16-180 s clip whole instead of trimming it to
    60 s. Passing it overrides the explicit ``min_sec``/``max_sec`` so the
    boundary stage stays in lock-step with the select-side envelope.
    """
    if duration_mode is not None:
        min_sec, max_sec = resolve_window(duration_mode)
    boundaries = build_boundary_set(
        words,
        silences=silences,
        scene_cuts=scene_cuts,
        silence_provider=silence_provider,
        scene_provider=scene_provider,
    )
    return snap_candidates(candidates, words, boundaries, min_sec=min_sec, max_sec=max_sec)


# --- Detection (ffmpeg silencedetect / PySceneDetect) ------------------------
# CONTRACT-NOTE: §5 names PySceneDetect for scene cuts and §7 mentions ffmpeg
# silencedetect for silence. These detectors keep the heavy work behind injectable
# seams: ``detect_silences`` runs ffmpeg (the ``run_silencedetect`` seam mirrors
# ``subprocess.run`` and is mocked in tests — no real ffmpeg/socket), and
# ``detect_scene_cuts`` lazily imports ``scenedetect`` INSIDE the function (the
# ``scene_detect`` seam is mocked in tests so PySceneDetect is never imported at
# module load). Production callers (the shortmaker orchestrator) bind these via the
# boundary seam; tests either mock the inner seam OR keep injecting known lists to
# ``build_boundary_set`` / ``snap_from_lists`` as before.
import re as _re

# Match ffmpeg silencedetect stderr lines: ``silence_start: 12.3`` /
# ``silence_end: 15.8 | silence_duration: 3.5`` (numbers may be negative-leading?).
_SILENCE_START_RE = _re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = _re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")

# Defaults for ffmpeg silencedetect (noise floor in dB, min silence seconds).
DEFAULT_SILENCE_NOISE_DB: float = -30.0
DEFAULT_SILENCE_MIN_SEC: float = 0.5


def build_silencedetect_argv(
    video_path: str,
    *,
    ffmpeg_path: str = "ffmpeg",
    noise_db: float = DEFAULT_SILENCE_NOISE_DB,
    min_silence_sec: float = DEFAULT_SILENCE_MIN_SEC,
) -> list[str]:
    """argv (list, never shell) for ffmpeg ``silencedetect`` over ``video_path``.

    ``silencedetect`` writes ``silence_start``/``silence_end`` lines to **stderr**;
    we decode the video to null so only the analysis runs. Paths with spaces are
    safe because each is a single argv element (CONTRACTS.md §6).
    """
    return [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-i",
        video_path,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
        "-f",
        "null",
        "-",
    ]


def parse_silencedetect(stderr: str) -> tuple[float, ...]:
    """Parse ffmpeg ``silencedetect`` stderr into silence-gap **midpoints**.

    Each ``silence_start``/``silence_end`` pair is one silent gap; the snap target
    is its midpoint (a natural place to cut). Unpaired starts (a trailing silence
    with no end before EOF) are ignored. Returns sorted, de-duplicated midpoints.
    """
    starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr)]
    ends = [float(m.group(1)) for m in _SILENCE_END_RE.finditer(stderr)]
    mids: set[float] = set()
    for start, end in zip(starts, ends, strict=False):
        if end > start:
            mids.add(round((start + end) / 2.0, 3))
    return tuple(sorted(mids))


# A subprocess seam mirroring ``subprocess.run`` (kept injectable so tests never
# spawn ffmpeg). The detector reads ``completed.stderr`` for the analysis lines.
SilenceRunner = Callable[..., Any]
# A scenedetect seam: (video_path) -> list of scene-cut timestamps (seconds).
# Injected in tests so the heavy ``scenedetect`` import never happens.
SceneDetector = Callable[[str], Sequence[float]]


def detect_silences(
    video_path: str,
    *,
    settings: dict[str, Any] | None = None,
    noise_db: float = DEFAULT_SILENCE_NOISE_DB,
    min_silence_sec: float = DEFAULT_SILENCE_MIN_SEC,
    run: SilenceRunner | None = None,
) -> tuple[float, ...]:
    """Return silence-gap midpoints for ``video_path`` via ffmpeg silencedetect.

    Runs ``ffmpeg ... -af silencedetect`` (argv list, no shell) and parses its
    stderr (CONTRACTS.md §7). ``run`` defaults to ``subprocess.run`` but is
    injectable so tests mock the subprocess; the ffmpeg binary is resolved through
    :mod:`media_studio.ffmpeg` so the bundled/PATH binary is used. A probe failure
    returns an empty tuple (boundary-snap then falls back to other targets) rather
    than raising — a missing silence list must not fail the whole pipeline.
    """
    import subprocess

    from .. import ffmpeg as _ffmpeg

    runner = run if run is not None else subprocess.run
    try:
        ffmpeg_bin = _ffmpeg.ffmpeg_path(settings)
    except Exception:  # noqa: BLE001 - no ffmpeg resolvable -> no silences
        log.warning("ffmpeg not found for silencedetect on %s", video_path)
        return ()
    argv = build_silencedetect_argv(
        video_path,
        ffmpeg_path=ffmpeg_bin,
        noise_db=noise_db,
        min_silence_sec=min_silence_sec,
    )
    try:
        completed = runner(argv, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001 - a probe failure must not crash snap
        log.warning("silencedetect failed for %s: %s", video_path, exc)
        return ()
    stderr = getattr(completed, "stderr", "") or ""
    return parse_silencedetect(stderr)


def _default_scene_detect(video_path: str, threshold: float = 27.0) -> Sequence[float]:
    """Default scene detector: PySceneDetect ``ContentDetector`` (lazy import).

    Imported INSIDE the function so importing this module never drags in
    ``scenedetect`` (CONTRACTS.md §6: pure-logic modules stay heavy-dep-free). The
    returned scene-cut timestamps are each scene's start time in seconds.
    """
    from scenedetect import ContentDetector, detect  # type: ignore  # pragma: no cover - prod seam

    scene_list = detect(video_path, ContentDetector(threshold=threshold))  # pragma: no cover - prod seam
    return [scene[0].get_seconds() for scene in scene_list]  # pragma: no cover - prod seam


def detect_scene_cuts(
    video_path: str,
    *,
    detector: SceneDetector | None = None,
    threshold: float = 27.0,
) -> tuple[float, ...]:
    """Return scene-change timestamps for ``video_path`` via PySceneDetect.

    ``detector`` defaults to :func:`_default_scene_detect` (which lazily imports
    ``scenedetect``); tests inject a fake so the heavy library is never imported.
    A detection failure returns an empty tuple rather than raising — a missing
    scene-cut list degrades the snap to other boundary sources, never crashes it.
    """
    detect_fn = detector if detector is not None else (lambda p: _default_scene_detect(p, threshold))
    try:
        cuts = detect_fn(video_path)
    except Exception as exc:  # noqa: BLE001 - detection failure must not crash snap
        log.warning("scene detection failed for %s: %s", video_path, exc)
        return ()
    return tuple(sorted({float(c) for c in cuts if isinstance(c, (int, float))}))
