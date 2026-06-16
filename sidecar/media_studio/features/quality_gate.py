"""Tier-1 video-QUALITY gate (Phase-8 WU5-adjacent late re-ranker).

A DOVER-style video-quality assessment (VQA) pass that DEMOTES shaky / blurry /
over-compressed clips in the final ranking. The model (DOVER-Mobile, manifest
component #5) is **S-Lab License 1.0 — non-commercial**, so it is *local-first*
and lives entirely behind an injectable seam; tests inject a fake scorer and the
heavy ``torch`` stack is never imported here. A permissive VQA can be swapped in
later by replacing the backend factory only.

Shape (mirrors diarize / reframe_claudeshorts):

  1. **Pure half (top of module, 100%-covered):** the :class:`QualityScore`
     frozen dataclass, the score-combine math, :func:`demote_factor` (a
     multiplicative relevance penalty clamped to a floor), and
     :func:`apply_quality_gate` (stamp ``qualityScore``, apply the demotion to a
     candidate's ``score``, re-rank). All plain numpy/stdlib.

  2. **Heavy half behind a Protocol :class:`DoverBackend`** (never imported at
     load): a real impl is built lazily by :func:`_default_backend_factory`
     (importing ``quality_gate_backend`` only at runtime). The pure runner asks
     the backend for a ``(technical, aesthetic)`` pair per clip.

  3. **Availability + offline gate:** :func:`compute_quality_scores` consults a
     ``models_present`` seam and :func:`offline.guard_network`. When the model is
     missing AND offline, it returns ``[]`` (degrade) — :func:`apply_quality_gate`
     then becomes a NO-OP (candidates unchanged, order preserved). The gate never
     fabricates a quality score it could not measure.

Frozen-contract notes (Wave-2 unified-scorer integration):
  * ``QualityScore.technical / .aesthetic / .overall`` are all NORMALIZED 0..1.
  * Times/units are unchanged; the gate only re-weights an existing ``score``.
  * Missing modality == empty score list == no-op gate (the silent/visual-only
    degrade rule applied to quality).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline

if TYPE_CHECKING:  # numpy is in the venv, but the runner stays numpy-free; the
    import numpy as np  # heavy DOVER stack (torch/onnx) is isolated in the backend.

log = get_logger("media_studio.features.quality_gate")

#: A Candidate per §3 — accept any mapping with the §3 keys (matches boundary.py
#: which also treats Candidate as an open dict so this module needs no shared edit).
Candidate = dict[str, Any]

#: Cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]

# --------------------------------------------------------------------------- #
# on-demand asset (manifest component #5 — DOVER-Mobile, S-Lab, local-only)
# --------------------------------------------------------------------------- #
DOVER_ASSET_NAME = "dover-mobile-quality"
DOVER_HF_REPO = "teowu/DOVER"
DOVER_SIZE_MB = 60

#: Default lower bound on the demotion multiplier: even the worst clip keeps this
#: fraction of its relevance, so the gate RE-RANKS rather than annihilates.
DEFAULT_FLOOR = 0.3

#: How technical vs aesthetic combine into the overall 0..1 quality. Technical
#: (sharpness/compression/shake) is weighted slightly higher because it is the
#: signal this gate exists to penalise; tweakable, sums to 1.0.
TECHNICAL_WEIGHT = 0.6
AESTHETIC_WEIGHT = 0.4


# --------------------------------------------------------------------------- #
# pure: the quality score + combine math
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QualityScore:
    """A clip's video-quality assessment, all components NORMALIZED 0..1.

    ``technical`` captures sharpness / compression / shake (1.0 = pristine);
    ``aesthetic`` captures composition / colour appeal (1.0 = beautiful);
    ``overall`` is their weighted combine (also 0..1). Frozen — callers build a
    new one rather than mutating (coding-style: immutability).
    """

    technical: float
    aesthetic: float
    overall: float


def combine_quality(technical: float, aesthetic: float) -> float:
    """Weighted, clamped combine of the two sub-scores into an overall 0..1.

    Each input is first clamped to ``[0, 1]`` (a backend may hand back a raw or
    very-slightly-out-of-range value); the result is the convex combination with
    :data:`TECHNICAL_WEIGHT` / :data:`AESTHETIC_WEIGHT` (already summing to 1.0),
    so it is itself guaranteed to land in ``[0, 1]``.
    """
    t = clamp(float(technical), 0.0, 1.0)
    a = clamp(float(aesthetic), 0.0, 1.0)
    return TECHNICAL_WEIGHT * t + AESTHETIC_WEIGHT * a


def make_quality_score(technical: float, aesthetic: float) -> QualityScore:
    """Build a clamped :class:`QualityScore` from a raw ``(technical, aesthetic)``.

    The single place sub-scores are normalised, so every ``QualityScore`` the
    rest of the module sees already obeys the 0..1 contract.
    """
    t = clamp(float(technical), 0.0, 1.0)
    a = clamp(float(aesthetic), 0.0, 1.0)
    return QualityScore(technical=t, aesthetic=a, overall=combine_quality(t, a))


def demote_factor(score: QualityScore, *, floor: float = DEFAULT_FLOOR) -> float:
    """Multiplicative relevance penalty in ``[floor, 1.0]`` from an overall score.

    A pristine clip (``overall == 1.0``) keeps full relevance (factor 1.0); a
    poor clip is scaled down toward ``floor`` (never below it, so a low-quality
    but topically-perfect clip is demoted, not deleted). ``floor`` itself is
    clamped to ``[0, 1]`` so a nonsensical caller value can't invert the gate.
    """
    f = clamp(float(floor), 0.0, 1.0)
    overall = clamp(float(score.overall), 0.0, 1.0)
    # Linear map overall in [0,1] -> factor in [floor,1]: at overall=1 -> 1.0,
    # at overall=0 -> floor.
    return f + (1.0 - f) * overall


def apply_quality_gate(
    candidates: list[Candidate],
    scores: Sequence[QualityScore],
    *,
    floor: float = DEFAULT_FLOOR,
) -> list[Candidate]:
    """Stamp ``qualityScore`` + demote each candidate's ``score``, then re-rank.

    Pairs ``candidates[i]`` with ``scores[i]``. Each result is a NEW dict (inputs
    never mutated): ``qualityScore`` = ``score.overall``; ``score`` is multiplied
    by :func:`demote_factor`. The list is then sorted by descending demoted score
    (ties keep input order — a stable sort) and renumbered ``rank`` 1..N.

    **No-op contract:** when ``scores`` is empty (the model was unavailable /
    offline-gated) the candidates are returned UNCHANGED in original order — the
    gate measured nothing, so it demotes nothing. A length mismatch likewise
    leaves any unpaired candidate untouched (its ``score``/order preserved).
    """
    if not scores:
        return list(candidates)

    demoted: list[tuple[int, float, Candidate]] = []
    for i, cand in enumerate(candidates):
        if i < len(scores):
            qs = scores[i]
            factor = demote_factor(qs, floor=floor)
            new_score = float(cand.get("score", 0.0)) * factor
            new_cand: Candidate = {
                **cand,
                "qualityScore": float(qs.overall),
                "score": new_score,
            }
            demoted.append((i, new_score, new_cand))
        else:
            # Unpaired candidate (more candidates than scores): keep as-is, but
            # give it its original score as the sort key so order is preserved.
            demoted.append((i, float(cand.get("score", 0.0)), dict(cand)))

    # Stable re-rank: highest demoted score first; ties fall back to input index.
    ordered = sorted(demoted, key=lambda row: (-row[1], row[0]))
    return [{**cand, "rank": idx + 1} for idx, (_i, _s, cand) in enumerate(ordered)]


# --------------------------------------------------------------------------- #
# the heavy backend seam (DOVER-Mobile) — never imported here
# --------------------------------------------------------------------------- #
class DoverBackend(Protocol):
    """The slice of the DOVER VQA model the runner needs.

    A real implementation (built lazily, never at import time) samples clip
    frames and returns a ``(technical, aesthetic)`` pair per clip. Tests inject a
    fake that returns hand-built tuples, so no model / weights / torch are
    touched. ``frames`` is the per-clip frame stack the loader produced.
    """

    def assess(self, frames: np.ndarray) -> tuple[float, float]:
        """Return a raw ``(technical, aesthetic)`` quality pair for one clip."""
        ...  # pragma: no cover - Protocol stub (the real body lives in the backend)


#: ``(path, candidates) -> per-clip frame stacks`` (cv2/decord lives INSIDE it).
FrameLoader = Callable[[str, Sequence[Candidate]], "list[np.ndarray]"]
#: ``settings -> DoverBackend`` — default lazily builds the real DOVER impl.
BackendFactory = Callable[[dict[str, Any]], DoverBackend]
#: ``settings -> bool`` — is the DOVER asset installed locally?
ModelsPresent = Callable[[dict[str, Any]], bool]


def compute_quality_scores(
    media_path: str,
    candidates: Sequence[Candidate],
    *,
    settings: dict[str, Any] | None = None,
    backend_factory: BackendFactory | None = None,
    frame_loader: FrameLoader | None = None,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> list[QualityScore]:
    """Assess each candidate clip -> a clamped :class:`QualityScore` (0..1 each).

    Seams (all injectable, defaults bind the real impls lazily):
      * ``backend_factory`` builds the heavy :class:`DoverBackend`;
      * ``frame_loader`` extracts per-clip frames (cv2/decord imported inside it);
      * ``models_present`` reports whether the DOVER asset is installed.

    **Degrade rule (the WU5 silent/missing path):** when the model is NOT present
    AND offline mode is on, a download would be needed — there is no way to
    measure quality, so this returns ``[]`` (the gate becomes a no-op). When the
    model is present it runs offline normally. An empty ``candidates`` list also
    returns ``[]`` (nothing to score). ``should_cancel`` stops the loop early and
    returns the scores gathered so far.
    """
    settings = settings or {}
    if not candidates:
        return []

    present = (models_present or default_models_present)(settings)
    # Degrade rule: missing model AND offline -> no way to measure quality, so
    # return no scores (the gate becomes a no-op) rather than fabricating or
    # hanging on a blocked download. Online-but-missing falls through: a real run
    # would fetch the weight via the lazy backend (the download is its concern).
    if not present and _offline.is_offline(settings):
        log.info("DOVER quality model absent + offline -> quality gate is a no-op")
        return []

    factory = backend_factory or _default_backend_factory
    loader = frame_loader or _default_frame_loader
    backend = factory(settings)
    clip_frames = loader(media_path, candidates)

    scores: list[QualityScore] = []
    total = max(len(candidates), 1)
    for idx, cand in enumerate(candidates):
        if should_cancel is not None and should_cancel():
            break
        frames = clip_frames[idx] if idx < len(clip_frames) else _empty_frames()
        technical, aesthetic = backend.assess(frames)
        scores.append(make_quality_score(technical, aesthetic))
        if on_progress is not None:
            on_progress((idx + 1) / total * 100.0, f"assessed clip {idx + 1}/{total}")
        _ = cand  # cand is the unit of work; frames are keyed by index above.
    return scores


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _empty_frames() -> np.ndarray:
    """A 0-frame stack for a clip the loader couldn't extract (degrade input)."""
    import numpy as np  # noqa: PLC0415 - numpy is a venv dep; kept out of the hot path

    return np.empty((0, 0, 0, 3), dtype=np.uint8)


def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the DOVER-Mobile asset is installed locally (no heavy import).

    Uses the asset manager's installed-detection so an already-cached snapshot
    counts — that is what lets the gate run offline once the weight is present.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
    from ..assets.manager import AssetManager  # noqa: PLC0415

    mgr = AssetManager(settings_provider=lambda: settings)
    entry = manifest.get_asset(DOVER_ASSET_NAME)
    if entry is None:
        return False
    return mgr.installed_path(entry) is not None


def _default_backend_factory(settings: dict[str, Any]) -> DoverBackend:
    """Build the real DOVER-Mobile backend (LAZY import; runtime only)."""
    from .quality_gate_backend import DoverMobileBackend  # noqa: PLC0415 - heavy seam

    return DoverMobileBackend(settings)


def _default_frame_loader(media_path: str, candidates: Sequence[Candidate]) -> list[np.ndarray]:
    """Extract per-clip frame stacks (the real cv2/decord loader; runtime only)."""
    from .quality_gate_backend import load_clip_frames  # noqa: PLC0415 - heavy seam

    return load_clip_frames(media_path, candidates)


__all__ = [
    "AESTHETIC_WEIGHT",
    "DEFAULT_FLOOR",
    "DOVER_ASSET_NAME",
    "DOVER_HF_REPO",
    "DOVER_SIZE_MB",
    "TECHNICAL_WEIGHT",
    "BackendFactory",
    "Candidate",
    "DoverBackend",
    "FrameLoader",
    "ModelsPresent",
    "QualityScore",
    "apply_quality_gate",
    "combine_quality",
    "compute_quality_scores",
    "default_models_present",
    "demote_factor",
    "make_quality_score",
]
