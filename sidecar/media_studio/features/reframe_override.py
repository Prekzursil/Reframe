"""Manual per-shot speaker / layout / crop override layer (WU R2).

This is the **PURE, dependency-free** decision layer that makes an imperfect
active-speaker-detection (ASD) result shippable (OpusClip-parity manual
correction). Given a per-shot reframe *plan* — derived from an R0
:class:`~media_studio.features.reframe_eval.ReframeTrace` (or, once it lands,
produced by the R1 multi-speaker engine) — a user can:

  * **flip** the chosen active speaker on a shot (to another candidate the
    detector found in that shot);
  * **switch** the per-shot layout (single / split / composite);
  * **nudge** the crop rectangle.

…and the module computes **exactly which shots changed** so a caller re-renders
**only those** shots, never the whole clip.

No video, no GPU, no model import — the heavy per-shot re-render is the R1
engine's job. This module produces the override-resolved plan + the affected-shot
index set that re-render must target, and is wired to 100% line+branch coverage on
synthetic, path-free fixtures (``tests/test_reframe_override.py``). Failures are
LOUD: a bad shot index, an unknown speaker/layout, or a degenerate crop raises
:class:`OverrideError` (never a silent no-op or center-crop fallback — GATE-2
"no silent fallbacks").

The wire shapes (camelCase) mirror the R0 trace contract:

  * ``ShotDecision``  -> ``{index, startFrame, endFrame, speaker, layout,
    crop:[x,y,w,h], speakers:[...]}``
  * ``ShotPlan``      -> ``{sourceWidth, sourceHeight, fps, shots:[ShotDecision]}``
  * ``ShotOverride``  -> ``{index, speaker?, layout?, crop?:[x,y,w,h]}``

RPCs (pure compose): ``reframe.shotPlan`` derives an editable plan from a trace;
``reframe.applyOverrides`` resolves overrides + returns the affected-shot set.

**v1.5 O-2 — the decision sidecar.** Those two RPCs were unreachable from the app:
``shotPlan`` needs a ``trace`` and NO renderer code could ever obtain one (the
multi-speaker engine built one in-process and threw it away). So the engine now
drops a small JSON *decision sidecar* next to every clip it renders —
``<clip>.reframe.json``, see :func:`build_decision_sidecar` — and
``reframe.shotPlanFor {clip}`` turns it into an editable plan. A clip the engine
never rendered has no sidecar and yields ``{"plan": null}``: an HONEST empty
state, so the UI can say "no per-shot decisions for this clip" instead of
mounting a correction panel over invented data. A sidecar that EXISTS but is
corrupt or of an unknown version is LOUD (never a silent skip).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .reframe_eval import (
    LAYOUTS,
    HarnessError,
    ReframeTrace,
    segments_to_per_frame,
)
from .reframe_eval import _as_float as _eval_as_float
from .reframe_eval import _as_int as _eval_as_int

#: The default layout assigned to a shot whose frames carry no concrete layout
#: label (only the ``"none"`` filler) — a single-speaker crop is the safe floor.
DEFAULT_LAYOUT = "single"

#: The decision-sidecar filename suffix — ``<rendered clip>.reframe.json``.
SIDECAR_SUFFIX = ".reframe.json"

#: The sidecar schema version. A sidecar written by a future/unknown schema is
#: REJECTED loudly rather than half-read (GATE-2 "no silent fallbacks").
SIDECAR_VERSION = 1

Crop = tuple[float, float, float, float]


class OverrideError(ValueError):
    """A plan/override contract violation — raised LOUDLY (never a silent no-op)."""


# --------------------------------------------------------------------------- #
# Data contract (frozen, immutable — coding-style: prefer immutable structures)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ShotDecision:
    """One shot's reframe decision: the chosen speaker, layout, and crop.

    * ``index`` — the shot's position in the plan (0-based, contiguous);
    * ``start_frame`` / ``end_frame`` — the shot's ``[start, end)`` frame span;
    * ``speaker`` — the chosen active-speaker id (``""`` = none / saliency crop);
    * ``layout`` — one of :data:`~media_studio.features.reframe_eval.LAYOUTS`;
    * ``crop`` — the crop rectangle ``(x, y, w, h)`` in source pixels;
    * ``speakers`` — the candidate speaker ids the detector found in this shot,
      in first-seen order (the set a user may flip the active speaker among).
    """

    index: int
    start_frame: int
    end_frame: int
    speaker: str
    layout: str
    crop: Crop
    speakers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """The camelCase wire object for this shot decision."""
        return {
            "index": self.index,
            "startFrame": self.start_frame,
            "endFrame": self.end_frame,
            "speaker": self.speaker,
            "layout": self.layout,
            "crop": list(self.crop),
            "speakers": list(self.speakers),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ShotDecision:
        """Validate + parse one shot decision wire object (loud on a bad shape)."""
        if not isinstance(raw, Mapping):
            raise OverrideError("shot must be a JSON object")
        layout = raw.get("layout")
        if layout not in LAYOUTS:
            raise OverrideError(f"shot layout must be one of {LAYOUTS}")
        return cls(
            index=_as_int(raw.get("index"), "shot.index"),
            start_frame=_as_int(raw.get("startFrame"), "shot.startFrame"),
            end_frame=_as_int(raw.get("endFrame"), "shot.endFrame"),
            speaker=_require_str(raw.get("speaker"), "shot.speaker"),
            layout=layout,
            crop=_parse_crop(raw.get("crop")),
            speakers=tuple(_require_str(s, "shot.speakers") for s in _seq(raw.get("speakers", []), "shot.speakers")),
        )


@dataclass(frozen=True)
class ShotPlan:
    """The full editable per-shot plan for one clip."""

    source_width: int
    source_height: int
    fps: float
    shots: tuple[ShotDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        """The camelCase wire object for this plan."""
        return {
            "sourceWidth": self.source_width,
            "sourceHeight": self.source_height,
            "fps": self.fps,
            "shots": [shot.to_dict() for shot in self.shots],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ShotPlan:
        """Validate + parse a plan wire object (loud on a bad shape)."""
        if not isinstance(raw, Mapping):
            raise OverrideError("plan must be a JSON object")
        width = _as_int(raw.get("sourceWidth"), "plan.sourceWidth")
        height = _as_int(raw.get("sourceHeight"), "plan.sourceHeight")
        if width <= 0 or height <= 0:
            raise OverrideError("plan source dimensions must be positive")
        fps = _as_float(raw.get("fps"), "plan.fps")
        if fps <= 0.0:
            raise OverrideError("plan fps must be > 0")
        shots = tuple(ShotDecision.from_dict(s) for s in _seq(raw.get("shots", []), "plan.shots"))
        return cls(source_width=width, source_height=height, fps=fps, shots=shots)


@dataclass(frozen=True)
class ShotOverride:
    """A user's patch to one shot — every field optional (absent = keep current)."""

    index: int
    speaker: str | None = None
    layout: str | None = None
    crop: Crop | None = None

    def to_dict(self) -> dict[str, Any]:
        """The camelCase wire object — absent fields are OMITTED, not nulled."""
        out: dict[str, Any] = {"index": self.index}
        if self.speaker is not None:
            out["speaker"] = self.speaker
        if self.layout is not None:
            out["layout"] = self.layout
        if self.crop is not None:
            out["crop"] = list(self.crop)
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> ShotOverride:
        """Validate + parse one override wire object (loud on a bad shape)."""
        if not isinstance(raw, Mapping):
            raise OverrideError("override must be a JSON object")
        speaker = raw.get("speaker")
        layout = raw.get("layout")
        crop = raw.get("crop")
        return cls(
            index=_as_int(raw.get("index"), "override.index"),
            speaker=None if speaker is None else _require_str(speaker, "override.speaker"),
            layout=None if layout is None else _require_str(layout, "override.layout"),
            crop=None if crop is None else _parse_crop(crop),
        )


# --------------------------------------------------------------------------- #
# Shared validation helpers
# --------------------------------------------------------------------------- #


def _as_int(value: Any, field: str) -> int:
    """:func:`reframe_eval._as_int`, surfacing the loud error as :class:`OverrideError`."""
    try:
        return _eval_as_int(value, field)
    except HarnessError as exc:
        raise OverrideError(str(exc)) from exc


def _as_float(value: Any, field: str) -> float:
    """:func:`reframe_eval._as_float`, surfacing the loud error as :class:`OverrideError`."""
    try:
        return _eval_as_float(value, field)
    except HarnessError as exc:
        raise OverrideError(str(exc)) from exc


def _seq(value: Any, field: str) -> list[Any]:
    """A JSON array (reject scalars and the str/bytes 'iterables')."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise OverrideError(f"{field} must be an array")
    return list(value)


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise OverrideError(f"{field} must be a string")
    return value


def _parse_crop(value: Any) -> Crop:
    nums = _seq(value, "crop")
    if len(nums) != 4:
        raise OverrideError("crop must be [x, y, w, h]")
    x, y, w, h = (_as_float(n, "crop") for n in nums)
    return (x, y, w, h)


# --------------------------------------------------------------------------- #
# Derive an editable plan from an R0 trace (pure)
# --------------------------------------------------------------------------- #


def _shot_spans(boundaries: Sequence[int], total_frames: int) -> list[tuple[int, int]]:
    """Split ``[0, total_frames)`` into ``[start, end)`` shots at ``boundaries``.

    Boundaries are de-duplicated, sorted, and clamped to ``(0, total_frames)``;
    a boundary at 0 or >= the frame count contributes no extra cut. The result is
    a clean contiguous partition (one shot when there are no interior cuts).
    """
    if total_frames <= 0:
        raise OverrideError("trace has no frames")
    cuts = sorted({int(b) for b in boundaries if 0 < int(b) < total_frames})
    spans: list[tuple[int, int]] = []
    start = 0
    for cut in cuts:
        spans.append((start, cut))
        start = cut
    spans.append((start, total_frames))
    return spans


def _majority_layout(labels: Sequence[str]) -> str:
    """The most-common concrete layout in ``labels`` (ties -> first seen);
    :data:`DEFAULT_LAYOUT` when the shot carries only the ``"none"`` filler."""
    counts = Counter(label for label in labels if label in LAYOUTS)
    if not counts:
        return DEFAULT_LAYOUT
    best = max(counts.values())
    # A non-empty Counter guarantees a first label whose count equals ``best``.
    return next(label for label in labels if label in LAYOUTS and counts[label] == best)


def _distinct(values: Sequence[str]) -> tuple[str, ...]:
    """Distinct values in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)


def _majority_speaker(speakers: Sequence[str]) -> str:
    """The most-common speaker id in ``speakers`` (ties -> first seen); ``""`` when empty."""
    if not speakers:
        return ""
    counts = Counter(speakers)
    best = max(counts.values())
    # A non-empty sequence guarantees a first speaker whose count equals ``best``.
    return next(speaker for speaker in speakers if counts[speaker] == best)


def plan_from_trace(
    trace: ReframeTrace | Mapping[str, Any],
    *,
    source_width: int,
    source_height: int,
    fps: float,
) -> ShotPlan:
    """Derive an editable :class:`ShotPlan` from an R0 reframe trace.

    Each shot (the run between detected cut boundaries) gets: the majority active
    speaker, the candidate speakers found in the shot, the majority concrete
    layout, and a representative crop (the crop at the shot's first frame). The
    trace's per-frame arrays must agree on length (loud otherwise).
    """
    parsed = trace if isinstance(trace, ReframeTrace) else ReframeTrace.from_dict(trace)
    if source_width <= 0 or source_height <= 0:
        raise OverrideError("source dimensions must be positive")
    if fps <= 0.0:
        raise OverrideError("fps must be > 0")
    total = len(parsed.speaker_per_frame)
    if len(parsed.crops) != total:
        raise OverrideError("trace crops and speakerPerFrame lengths differ")
    layout_per_frame = segments_to_per_frame(parsed.segments, total)
    shots: list[ShotDecision] = []
    for index, (start, end) in enumerate(_shot_spans(parsed.shot_boundaries, total)):
        window_speakers = parsed.speaker_per_frame[start:end]
        shots.append(
            ShotDecision(
                index=index,
                start_frame=start,
                end_frame=end,
                speaker=_majority_speaker(window_speakers),
                layout=_majority_layout(layout_per_frame[start:end]),
                crop=parsed.crops[start],
                speakers=_distinct(window_speakers),
            )
        )
    return ShotPlan(source_width=source_width, source_height=source_height, fps=fps, shots=tuple(shots))


# --------------------------------------------------------------------------- #
# The decision sidecar (v1.5 O-2) — how a trace REACHES the renderer
# --------------------------------------------------------------------------- #


def sidecar_path(clip: str) -> str:
    """The decision-sidecar path for a rendered ``clip`` (``<clip>.reframe.json``)."""
    return f"{clip}{SIDECAR_SUFFIX}"


def trace_to_dict(trace: ReframeTrace) -> dict[str, Any]:
    """Serialise an R0 :class:`ReframeTrace` to its camelCase wire object.

    The exact inverse of :meth:`ReframeTrace.from_dict` (which the R0 module
    ships without a serialiser), so a persisted sidecar round-trips.
    """
    return {
        "shotBoundaries": list(trace.shot_boundaries),
        "speakerPerFrame": list(trace.speaker_per_frame),
        "segments": [
            {"startFrame": seg.start_frame, "endFrame": seg.end_frame, "layout": seg.layout} for seg in trace.segments
        ],
        "crops": [list(crop) for crop in trace.crops],
    }


def build_decision_sidecar(
    *,
    engine: str,
    aspect: str,
    source_path: str,
    source_width: int,
    source_height: int,
    fps: float,
    trace: ReframeTrace,
) -> dict[str, Any]:
    """The sidecar payload an engine drops next to a clip it just rendered.

    It carries EVERYTHING a later correction round needs without re-running the
    ML analysis: the source clip the crops are expressed against, its geometry,
    the aspect the engine targeted, and the per-frame trace the editable plan is
    derived from.
    """
    return {
        "version": SIDECAR_VERSION,
        "engine": engine,
        "aspect": aspect,
        "sourcePath": source_path,
        "sourceWidth": source_width,
        "sourceHeight": source_height,
        "fps": fps,
        "trace": trace_to_dict(trace),
    }


def _read_text(path: str) -> str:
    """Default sidecar reader (the injectable seam's production implementation)."""
    return Path(path).read_text(encoding="utf-8")


def load_decision_sidecar(clip: str, *, read_text: Callable[[str], str] = _read_text) -> dict[str, Any] | None:
    """Load ``clip``'s decision sidecar; ``None`` when the clip has none.

    ABSENT is a legitimate state (the clip was rendered by an engine that emits
    no per-shot decisions), so it returns ``None`` rather than raising. A sidecar
    that EXISTS but is unreadable — bad JSON, not an object, or an unknown schema
    version — is a LOUD :class:`OverrideError`; half-reading it would be exactly
    the silent fallback GATE-2 forbids.
    """
    try:
        raw = read_text(sidecar_path(clip))
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise OverrideError(f"reframe sidecar is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise OverrideError("reframe sidecar must be a JSON object")
    version = payload.get("version")
    if version != SIDECAR_VERSION:
        raise OverrideError(f"unsupported reframe sidecar version {version!r}")
    return dict(payload)


def sidecar_overrides(payload: Mapping[str, Any]) -> tuple[ShotOverride, ...]:
    """The corrections already persisted into ``payload`` (empty when none)."""
    return tuple(ShotOverride.from_dict(o) for o in _seq(payload.get("overrides", []), "sidecar.overrides"))


def plan_from_sidecar(payload: Mapping[str, Any]) -> ShotPlan:
    """Derive the editable :class:`ShotPlan` from a loaded sidecar payload.

    Corrections from earlier rounds are REPLAYED onto the trace-derived plan, so
    the panel opens on what was last rendered — while the untouched trace keeps
    every candidate speaker, so the user can keep flipping.
    """
    base = plan_from_trace(
        payload.get("trace", {}),
        source_width=_as_int(payload.get("sourceWidth"), "sidecar.sourceWidth"),
        source_height=_as_int(payload.get("sourceHeight"), "sidecar.sourceHeight"),
        fps=_as_float(payload.get("fps"), "sidecar.fps"),
    )
    return apply_shot_overrides(base, sidecar_overrides(payload))


def with_overrides(payload: Mapping[str, Any], overrides: Sequence[ShotOverride]) -> dict[str, Any]:
    """``payload`` with ``overrides`` persisted, merged by shot index (new wins).

    Every override is ABSOLUTE (it carries the whole decision, never a delta), so
    replaying the merged set is idempotent and a later round can start from it.
    """
    merged = {o.index: o.to_dict() for o in sidecar_overrides(payload)}
    merged.update({o.index: o.to_dict() for o in overrides})
    return {**payload, "overrides": [merged[index] for index in sorted(merged)]}


def speaker_candidate_crops(trace: ReframeTrace, shot: ShotDecision) -> dict[str, Crop]:
    """The crop the detector used for each candidate speaker within ``shot``.

    First-seen wins, matching :func:`_distinct`'s candidate ordering. This is what
    lets a speaker FLIP actually move the crop: the panel records only the chosen
    speaker id, and this recovers the rectangle the detector had for them.
    """
    crops: dict[str, Crop] = {}
    for frame in range(shot.start_frame, shot.end_frame):
        crops.setdefault(trace.speaker_per_frame[frame], trace.crops[frame])
    return crops


def resolved_crop(base: ShotDecision, resolved: ShotDecision, candidates: Mapping[str, Crop]) -> Crop:
    """The crop a re-render must use for ``resolved``.

    A hand-moved / zoomed rectangle is literal user intent and always wins. A pure
    speaker FLIP carries no crop edit, so the crop follows the newly chosen
    speaker — otherwise "flip the speaker" would re-render the same wrong face.
    A speaker with no recorded crop keeps the current rectangle.
    """
    if resolved.crop != base.crop:
        return resolved.crop
    if resolved.speaker != base.speaker:
        return candidates.get(resolved.speaker, resolved.crop)
    return resolved.crop


def effective_overrides(
    base: ShotPlan,
    resolved: ShotPlan,
    trace: ReframeTrace,
) -> tuple[ShotOverride, ...]:
    """One ABSOLUTE override per changed shot, with the crop fully resolved.

    The output is what a re-render renders AND what the sidecar persists, so the
    plan the panel re-opens on always matches the pixels that were produced.
    """
    changed = set(affected_shot_indices(base, resolved))
    return tuple(
        ShotOverride(
            index=after.index,
            speaker=after.speaker,
            layout=after.layout,
            crop=resolved_crop(before, after, speaker_candidate_crops(trace, before)),
        )
        for before, after in zip(base.shots, resolved.shots, strict=True)
        if after.index in changed
    )


# --------------------------------------------------------------------------- #
# Apply overrides + compute the affected-shot set (pure)
# --------------------------------------------------------------------------- #


def _clamp_crop(crop: Crop, width: int, height: int) -> Crop:
    """Clamp a crop into the source frame; loud on a non-positive width/height.

    A degenerate (zero/negative-sized) crop is a hard error, not a silent fixup —
    there is no sensible frame to render from it. Position+size are clamped so the
    rectangle stays fully inside ``[0, width] x [0, height]``.
    """
    x, y, w, h = crop
    if w <= 0 or h <= 0:
        raise OverrideError("crop width and height must be positive")
    w = min(w, float(width))
    h = min(h, float(height))
    x = min(max(x, 0.0), float(width) - w)
    y = min(max(y, 0.0), float(height) - h)
    return (x, y, w, h)


def _apply_one(shot: ShotDecision, override: ShotOverride, width: int, height: int) -> ShotDecision:
    """Return ``shot`` patched by ``override`` (immutable; loud on invalid values)."""
    changes: dict[str, Any] = {}
    if override.speaker is not None:
        if override.speaker not in shot.speakers:
            raise OverrideError(
                f"speaker {override.speaker!r} is not a candidate for shot {shot.index} {shot.speakers}"
            )
        changes["speaker"] = override.speaker
    if override.layout is not None:
        if override.layout not in LAYOUTS:
            raise OverrideError(f"layout must be one of {LAYOUTS}")
        changes["layout"] = override.layout
    if override.crop is not None:
        changes["crop"] = _clamp_crop(override.crop, width, height)
    return replace(shot, **changes)


def apply_shot_overrides(plan: ShotPlan, overrides: Sequence[ShotOverride]) -> ShotPlan:
    """Resolve ``overrides`` onto ``plan``, returning a NEW plan (immutable).

    Each override targets one shot by ``index``. An unknown index or a duplicate
    override for the same index raises (loud); an invalid speaker/layout/crop
    raises in :func:`_apply_one`. Shots with no override are unchanged.
    """
    by_index: dict[int, ShotOverride] = {}
    valid = {shot.index for shot in plan.shots}
    for override in overrides:
        if override.index not in valid:
            raise OverrideError(f"override targets unknown shot index {override.index}")
        if override.index in by_index:
            raise OverrideError(f"duplicate override for shot index {override.index}")
        by_index[override.index] = override
    shots = tuple(
        _apply_one(shot, by_index[shot.index], plan.source_width, plan.source_height)
        if shot.index in by_index
        else shot
        for shot in plan.shots
    )
    return replace(plan, shots=shots)


def affected_shot_indices(base: ShotPlan, resolved: ShotPlan) -> tuple[int, ...]:
    """The indices of shots whose speaker / layout / crop changed.

    This is the EXACT set a caller must re-render — never the whole clip. The two
    plans must describe the same shots (same length + indices), else it is loud.
    """
    if len(base.shots) != len(resolved.shots):
        raise OverrideError("plans have a different number of shots")
    affected: list[int] = []
    for before, after in zip(base.shots, resolved.shots, strict=True):
        if before.index != after.index:
            raise OverrideError("plans describe different shots")
        if (before.speaker, before.layout, before.crop) != (after.speaker, after.layout, after.crop):
            affected.append(after.index)
    return tuple(affected)


# --------------------------------------------------------------------------- #
# RPC (pure compose)
# --------------------------------------------------------------------------- #


def register(
    *,
    register_fn: Callable[[str, Callable[..., Any]], None],
    read_text: Callable[[str], str] = _read_text,
) -> None:
    """Register the three ``reframe.*`` override methods (pure compose).

    ``register_fn`` is ``protocol.register`` in production; tests pass a fake
    registrar. ``read_text`` is the sidecar-read seam (a real file read in
    production, a stub in tests). No method runs a heavy engine:

    * ``reframe.shotPlan``      — plan from a caller-supplied trace;
    * ``reframe.shotPlanFor``   — plan from the clip's persisted decision
      sidecar (v1.5 O-2: the renderer has no other way to get a trace);
    * ``reframe.applyOverrides`` — resolve a user's edits -> affected-shot set.
    """

    def reframe_shot_plan(params: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        """``reframe.shotPlan({trace, sourceWidth, sourceHeight, fps})`` -> plan."""
        try:
            plan = plan_from_trace(
                params.get("trace", {}),
                source_width=_as_int(params.get("sourceWidth"), "sourceWidth"),
                source_height=_as_int(params.get("sourceHeight"), "sourceHeight"),
                fps=_as_float(params.get("fps"), "fps"),
            )
            return {"plan": plan.to_dict()}
        except OverrideError as exc:
            raise _invalid_params(exc) from exc

    def reframe_apply_overrides(params: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        """``reframe.applyOverrides({plan, overrides})`` -> {plan, affected}."""
        try:
            base = ShotPlan.from_dict(params.get("plan"))
            overrides = [ShotOverride.from_dict(o) for o in _seq(params.get("overrides", []), "overrides")]
            resolved = apply_shot_overrides(base, overrides)
            return {"plan": resolved.to_dict(), "affected": list(affected_shot_indices(base, resolved))}
        except OverrideError as exc:
            raise _invalid_params(exc) from exc

    def reframe_shot_plan_for(params: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        """``reframe.shotPlanFor({clip})`` -> ``{plan|null, engine, aspect}``.

        ``plan: null`` is the honest "this clip carries no per-shot decisions"
        answer (no sidecar), NOT an error — the UI renders an explanation
        instead of a correction panel it could not honour.
        """
        try:
            clip = _require_str(params.get("clip"), "clip")
            payload = load_decision_sidecar(clip, read_text=read_text)
            if payload is None:
                return {"plan": None, "engine": "", "aspect": ""}
            return {
                "plan": plan_from_sidecar(payload).to_dict(),
                "engine": _require_str(payload.get("engine", ""), "sidecar.engine"),
                "aspect": _require_str(payload.get("aspect", ""), "sidecar.aspect"),
            }
        except OverrideError as exc:
            raise _invalid_params(exc) from exc

    register_fn("reframe.shotPlan", reframe_shot_plan)
    register_fn("reframe.shotPlanFor", reframe_shot_plan_for)
    register_fn("reframe.applyOverrides", reframe_apply_overrides)


def _invalid_params(exc: OverrideError) -> Exception:
    """Map an :class:`OverrideError` to the RPC INVALID_PARAMS error (loud)."""
    from ..protocol import ErrorCode, RpcError

    return RpcError(str(exc), ErrorCode.INVALID_PARAMS)
