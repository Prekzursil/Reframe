"""UNIFIED TRI-MODAL SCORER — the Wave-2 fusion engine (Phase-8).

This is where the 9 Wave-1 signal channels (visual + audio), the scene-cut
boundary signal, the learned LGBMRanker re-rank, DPP/MMR diversity, the optional
DOVER quality gate, and the optional Tier-2 SmolVLM2 re-rank are *combined* with
the existing transcript/LLM selection path. The thin public entry point is
``select.select_unified`` which delegates the fusion math here; keeping the
fusion in a sibling module preserves ``select.py``'s frozen-100% transcript path
and isolates the new branch matrix.

Why a sibling module (not inside ``select.py``)? ``select.py`` today is a *pure
transcript + LLM* path that is 100% line+branch covered, and the contract is to
leave its existing functions byte-unchanged. All the new fusion branches —
window pooling, the degrade re-normalization, the silent-video peak-pick, the
tier gating — live here so they get their own clean 100% surface.

Design invariants (frozen):

* **Frozen channel vocabulary** — the visual/audio channels exactly match
  ``ranker.SIGNAL_FEATURES`` (``motion, saliency, aesthetic, zeroShot, novelty,
  audioSalience, laughter, applause, music, loudness``), so a pooled per-clip
  :class:`~media_studio.features.ranker.SignalMap` drops straight into
  ``ranker.build_feature_row``. ``sceneCut`` is a *boundary* signal, not a ranker
  feature column — it is consumed by boundary-snap / window-edge weighting, never
  pooled into the ranker vector.
* **Degrade by re-normalization (the §-signal rule, ONE code path):** a track
  with ``present=False`` is dropped from the weighted mean AND from the
  denominator, so a silent clip is judged on the visual weights alone, a no-model
  machine on whatever channels survive — never on fabricated zeros. Enforced
  once, in :func:`window_interest_curve` / :func:`pool_signals_for_window`, so all
  three tiers inherit it.
* **Pure numpy/stdlib only** — NO heavy imports here. The only "seams" are the
  injected objects (``tracks``, ``ranker``, ``quality_scores``, ``vlm_reranker``);
  no model is ever loaded in this module. Tests drive every branch with
  hand-built :class:`SignalTrack`-shaped objects and fake ranker/vlm seams.

The :class:`SignalTrack` shape is duck-typed: every Wave-1 module emits its own
structurally-identical frozen ``SignalTrack`` (``.channel``, ``.signals``,
``.present``) of ``Signal`` (``.channel``, ``.start``, ``.end``, ``.value``), all
on the shared 1-second ``sample_windows`` grid. This module reads only those
attributes, so it consumes any of them without a shared base class.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from .ranker import SIGNAL_FEATURES

if TYPE_CHECKING:  # numpy IS in the venv; kept import-light, used only in fallbacks.
    import numpy as np

log = get_logger("media_studio.features.scorer")

#: The shared 1-second window grid all Wave-1 tracks are emitted on.
WINDOW_SEC: float = 1.0

#: Default per-channel blend weights (overridable via ``settings["scorerWeights"]``).
#: Keyed by the frozen channel vocabulary; the denominator in the weighted mean is
#: the SUM of the weights of the channels actually PRESENT (the degrade rule), so
#: a missing channel never contributes a fabricated zero.
DEFAULT_WEIGHTS: dict[str, float] = {
    "motion": 0.8,
    "saliency": 1.2,
    "aesthetic": 1.0,
    "zeroShot": 1.3,
    "novelty": 0.7,
    "audioSalience": 1.2,
    "laughter": 1.1,
    "applause": 1.0,
    "music": 0.4,
    "loudness": 0.6,
}

#: Default blend factor for :func:`fuse_score`: how much the signal boost pulls the
#: working relevance away from the legacy LLM score (0 = pure LLM, 1 = pure signal).
DEFAULT_FUSE_ALPHA: float = 0.5


# --------------------------------------------------------------------------- #
# duck-typed SignalTrack contract (every Wave-1 module emits this exact shape)
# --------------------------------------------------------------------------- #
class _SignalLike(Protocol):
    """The slice of a Wave-1 ``Signal`` this module reads."""

    start: float
    end: float
    value: float


class _TrackLike(Protocol):
    """The slice of a Wave-1 ``SignalTrack`` this module reads (duck-typed)."""

    channel: str
    present: bool
    signals: Sequence[_SignalLike]


#: The candidate shape (matches ``select.Candidate`` / ``boundary.Candidate``: an
#: open mapping with at least the §3 keys). Kept as a plain dict for wire-symmetry.
Candidate = dict[str, Any]


# --------------------------------------------------------------------------- #
# the Tier-2 VLM re-rank seam (structurally identical to smolvlm2.VlmReranker)
# --------------------------------------------------------------------------- #
class VlmReranker(Protocol):
    """The Tier-2 re-rank seam :func:`select.select_unified` step 6 consumes.

    ``smolvlm2.SmolVlmReranker`` satisfies this structurally (duck-typed). The
    step is invoked only when ``tier >= 2`` AND a reranker is injected, so the
    default pipeline never loads the video-LLM.
    """

    def rerank_top_k(self, cands: Sequence[Mapping[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
        """Reorder the top ``top_k`` candidates; the tail is left untouched."""
        ...  # pragma: no cover - Protocol stub, never executed


# --------------------------------------------------------------------------- #
# pure: per-window / per-clip signal pooling (the degrade rule lives here)
# --------------------------------------------------------------------------- #
def present_channels(tracks: Mapping[str, _TrackLike]) -> tuple[str, ...]:
    """The channel names whose track is PRESENT (degrade drops the rest).

    Returns the names in :data:`DEFAULT_WEIGHTS` order (the frozen vocabulary),
    filtered to the tracks that exist in ``tracks`` and report ``present=True``.
    A channel ``tracks`` doesn't carry, or carries with ``present=False``, is
    omitted — never zeroed.
    """
    out: list[str] = []
    for channel in DEFAULT_WEIGHTS:
        track = tracks.get(channel)
        if track is not None and track.present:
            out.append(channel)
    return tuple(out)


def _mean_in_window(track: _TrackLike, start: float, end: float) -> float | None:
    """Mean of a track's signal values whose window overlaps ``[start, end)``.

    A signal overlaps when its ``[sig.start, sig.end)`` intersects ``[start, end)``
    (an instantaneous window with ``sig.start == sig.end`` overlaps when it sits
    inside the clip). Returns ``None`` when NO signal overlaps (the channel
    contributes nothing for this clip — it is then omitted, not zeroed).
    """
    values: list[float] = []
    for sig in track.signals:
        s, e = float(sig.start), float(sig.end)
        overlaps = s < end and e > start if e > s else (start <= s < end)
        if overlaps:
            values.append(clamp(float(sig.value), 0.0, 1.0))
    if not values:
        return None
    return sum(values) / float(len(values))


def pool_signals_for_window(tracks: Mapping[str, _TrackLike], start: float, end: float) -> dict[str, float]:
    """Per-channel MEAN of the in-``[start, end)`` signals of each PRESENT track.

    A track that is absent (not in ``tracks``), reports ``present=False``, or has
    no signal overlapping the window is OMITTED from the result (not zeroed) — the
    §-signal degrade rule applied at pooling time. The returned map keys are the
    surviving channel names; values are 0..1.
    """
    pooled: dict[str, float] = {}
    for channel in present_channels(tracks):
        track = tracks[channel]
        mean = _mean_in_window(track, start, end)
        if mean is not None:
            pooled[channel] = mean
    return pooled


def clip_signal_map(tracks: Mapping[str, _TrackLike], start: float, end: float) -> dict[str, float]:
    """The per-clip :class:`~media_studio.features.ranker.SignalMap` for ``[start, end)``.

    Restricted to the ranker's frozen :data:`~media_studio.features.ranker.SIGNAL_FEATURES`
    columns (so it drops straight into ``ranker.build_feature_row``): the
    boundary-only ``sceneCut`` channel is never included even if present. Only
    channels that are PRESENT and have an overlapping signal appear — missing
    channels are omitted (the ranker zeroes them at featurization).
    """
    pooled = pool_signals_for_window(tracks, start, end)
    return {ch: pooled[ch] for ch in SIGNAL_FEATURES if ch in pooled}


def _weighted_present_mean(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted mean over the PRESENT channels, re-normalized by present weights.

    ``sum(w_c * v_c) / sum(w_c)`` over only the channels in ``values``; an empty
    map (no present channel) yields ``0.0`` (nothing measured). This is the one
    place the degrade re-normalization is enforced.
    """
    num = 0.0
    den = 0.0
    for channel, value in values.items():
        weight = float(weights.get(channel, 0.0))
        num += weight * clamp(float(value), 0.0, 1.0)
        den += weight
    if den <= 0.0:
        return 0.0
    return clamp(num / den, 0.0, 1.0)


def window_interest_curve(
    tracks: Mapping[str, _TrackLike],
    duration: float,
    *,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    window_sec: float = WINDOW_SEC,
) -> list[float]:
    """Per-1s-window fused interestingness curve (0..1), one value per window.

    For each ``window_sec``-long window over ``[0, duration]``, pools the present
    channels (:func:`pool_signals_for_window`) and takes the weighted mean
    re-normalized by the present weights (:func:`_weighted_present_mean`) — so a
    silent clip is scored on the visual weights alone and a no-model machine on
    whatever survives, never on fabricated zeros. A non-positive ``duration`` (or a
    non-positive ``window_sec``) yields an empty curve.
    """
    d = max(0.0, float(duration))
    step = float(window_sec)
    if d <= 0.0 or step <= 0.0:
        return []
    curve: list[float] = []
    start = 0.0
    while start < d:
        end = min(start + step, d)
        pooled = pool_signals_for_window(tracks, start, end)
        curve.append(_weighted_present_mean(pooled, weights))
        start += step
    return curve


# --------------------------------------------------------------------------- #
# pure: the silent-video candidate path (peak-pick the fused curve)
# --------------------------------------------------------------------------- #
def candidates_from_curve(
    curve: Sequence[float],
    duration: float,
    controls: Any | None,
    tracks: Mapping[str, _TrackLike],
    *,
    window_sec: float = WINDOW_SEC,
) -> list[dict[str, Any]]:
    """Peak-pick the fused interest ``curve`` into clip candidates (silent path).

    The visual-only candidate generator used when there is no transcript / no LLM
    provider (WU5 acceptance). Picks the windows by descending fused interest,
    greedily skipping any that overlap an already-chosen clip's ``[min,max]``
    window, and synthesizes each Candidate via :func:`select.to_candidates` so the
    duration clamp + factor + percentile machinery downstream still apply. Per-clip
    ``factors`` are synthesized from the window's interest (so the ranker /
    percentile have a real signal), ``hook=""`` and ``why="visual interest peak"``.

    Returns ``[]`` when the curve is empty (nothing to peak-pick).
    """
    from .select import _resolve_controls, to_candidates  # noqa: PLC0415 - avoid import cycle

    cfg = _resolve_controls(dict(controls) if isinstance(controls, Mapping) else None)  # type: ignore[arg-type]
    count, min_sec = cfg["count"], cfg["min_sec"]
    d = max(0.0, float(duration))
    n = len(curve)
    if n == 0:
        return []

    # Pick window indices best-first (stable on ties via the index tiebreak).
    order = sorted(range(n), key=lambda i: (-float(curve[i]), i))
    chosen: list[int] = []
    occupied: list[tuple[float, float]] = []
    for idx in order:
        if len(chosen) >= count:
            break
        start = idx * window_sec
        end = min(start + min_sec, d) if d > 0.0 else start + min_sec
        # Greedy non-overlap against already-chosen clip spans.
        if any(start < oe and end > os for os, oe in occupied):
            continue
        chosen.append(idx)
        occupied.append((start, end))

    raw_clips: list[dict[str, Any]] = []
    for idx in chosen:
        win_start = idx * window_sec
        interest = clamp(float(curve[idx]), 0.0, 1.0)
        factor_pct = int(round(interest * 100.0))
        raw_clips.append(
            {
                "start": win_start,
                "end": win_start + min_sec,
                "score": factor_pct,
                "hook": "",
                "why": "visual interest peak",
                "factors": dict.fromkeys(
                    ("hookStrength", "emotionalFlow", "perceivedValue", "shareability"), factor_pct
                ),
            }
        )

    cands = to_candidates(raw_clips, cfg["min_sec"], cfg["max_sec"], d if d > 0.0 else None)
    # to_candidates does not carry the synthesized ``signals`` map through and may
    # SHIFT a clip's [start,end) when clamping against the source duration, so the
    # honest per-clip signal map is re-pooled over each FINAL span (not the raw
    # window) before the ranker / feedback flywheel reads it.
    out: list[dict[str, Any]] = []
    for cand in cands:
        row: dict[str, Any] = dict(cand)
        row["signals"] = clip_signal_map(tracks, float(cand["start"]), float(cand["end"]))
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# pure: score fusion (blend the legacy LLM score with the signal boost)
# --------------------------------------------------------------------------- #
def fuse_score(legacy_score_0_100: int, signal_boost_0_1: float, alpha: float = DEFAULT_FUSE_ALPHA) -> float:
    """Blend the legacy 0-100 LLM score with a 0..1 signal boost into a 0..1 score.

    ``(1 - alpha) * (legacy / 100) + alpha * boost``, all clamped: ``alpha`` is the
    weight given to the multimodal signal (0 = pure LLM, 1 = pure signal). The
    legacy score is rescaled to 0..1; the result is a 0..1 working relevance the
    diversity / ranker stages consume (the legacy ``score`` field is left frozen).
    """
    a = clamp(float(alpha), 0.0, 1.0)
    legacy_unit = clamp(float(legacy_score_0_100) / 100.0, 0.0, 1.0)
    boost = clamp(float(signal_boost_0_1), 0.0, 1.0)
    return clamp((1.0 - a) * legacy_unit + a * boost, 0.0, 1.0)


def signal_boost_for_clip(
    tracks: Mapping[str, _TrackLike],
    start: float,
    end: float,
    *,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> float:
    """The weighted-present-mean signal boost (0..1) for a clip's ``[start, end)``.

    Pools the present channels over the clip span and re-normalizes by present
    weights (same degrade rule as the window curve). A clip with no present
    overlapping signal yields ``0.0`` (no boost — the legacy score stands alone).
    """
    pooled = pool_signals_for_window(tracks, start, end)
    return _weighted_present_mean(pooled, weights)


# --------------------------------------------------------------------------- #
# pure: the diversity-embeddings fallback (signal-vector matrix, zero models)
# --------------------------------------------------------------------------- #
def fallback_embeddings(candidates: Sequence[Mapping[str, Any]], tracks: Mapping[str, _TrackLike]) -> np.ndarray:
    """A zero-model embedding matrix for diversity from each clip's pooled signals.

    When the WU4 ``novelty`` embeddings are unavailable, dedup still needs a
    per-candidate feature matrix: build one row per candidate from its
    :func:`clip_signal_map` over the frozen :data:`~media_studio.features.ranker.SIGNAL_FEATURES`
    columns (missing channels -> 0.0). Shape ``(n, len(SIGNAL_FEATURES))``; an
    empty candidate list yields a ``(0, len(SIGNAL_FEATURES))`` matrix. numpy is a
    venv dep, imported lazily to keep the module's public import surface light.
    """
    import numpy as np  # noqa: PLC0415 - numpy is a venv dep; kept out of import time

    rows: list[list[float]] = []
    for cand in candidates:
        sig = clip_signal_map(tracks, float(cand.get("start", 0.0) or 0.0), float(cand.get("end", 0.0) or 0.0))
        rows.append([float(sig.get(ch, 0.0)) for ch in SIGNAL_FEATURES])
    if not rows:
        return np.zeros((0, len(SIGNAL_FEATURES)), dtype=np.float64)
    return np.asarray(rows, dtype=np.float64)


__all__ = [
    "DEFAULT_FUSE_ALPHA",
    "DEFAULT_WEIGHTS",
    "WINDOW_SEC",
    "Candidate",
    "VlmReranker",
    "candidates_from_curve",
    "clip_signal_map",
    "fallback_embeddings",
    "fuse_score",
    "pool_signals_for_window",
    "present_channels",
    "signal_boost_for_clip",
    "window_interest_curve",
]
