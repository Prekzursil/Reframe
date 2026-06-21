"""Engine facade — one stable, transport-agnostic import surface for features.

The feature modules under ``media_studio/features/`` are the real implementations;
this module is a thin *facade* that re-exports their stable entry points so callers
(other features, scripts, the Electron side, future RPC/SDK/CLI wiring, tests)
depend on ONE place instead of reaching into individual feature modules or the
JSON-RPC wire shape. A refactor inside a feature module never breaks a caller as
long as the facade handle is preserved.

Three complementary surfaces live here, all purely wiring (no behavior):

1. **Namespaced facades** (captions-export) — frozen ``@dataclass`` singletons
   grouping a feature's stable callables under a short handle::

       from media_studio import engine
       track = engine.subtitles.stack_bilingual(orig, translated)
       path  = engine.nle.export(clips, "out.edl", fmt="edl", fps=30)
       res   = engine.package.package(clip, "bundle.zip", meta=meta)

2. **Flat re-exports** (audio-stabilize) — top-level names:

   * **Stabilization** (camera-shake, ffmpeg vidstab 2-pass):
       ``stabilize_clip`` / ``StabilizeEngine`` / ``stabilize_available``
   * **A/V merge + auto-duck + EBU R128 loudnorm**:
       ``build_audio_mix_argv`` / ``AudioMix`` / ``build_loudnorm_argv``
   * **Silence-trim / dead-air removal**:
       ``trim_silence`` / ``detect_silence_spans`` / ``keep_spans``

3. **Flat re-exports** (system-advanced) — top-level names:

   * **OFFLINE** ``is_offline`` / ``guard_network`` / ``enforce_offline_env``
   * **HEALTH**  ``Health`` / ``parse_ffmpeg_version`` / ``ML_BACKENDS``
   * **RECIPES** ``RecipeStore`` / ``normalize_recipe`` / ``resolve_refs``
   * **DIARIZE** ``diarize_transcript`` / ``greedy_cluster`` / ``speaker_label``

It is deliberately import-light: the feature modules keep ffmpeg / faster-whisper /
scenedetect / speechbrain / torch / provider / network deps behind their own lazy
seams, so importing this facade is side-effect-free. Adding a feature = add its
import + (a namespace or flat re-export) + its ``__all__`` entry. No behavior lives
here; it is purely a wiring layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .features import audio_saliency as _audio_saliency
from .features import caption_polish as _caption_polish
from .features import ctc_align as _ctc_align
from .features import diarize as _diarize
from .features import diversity as _diversity
from .features import health as _health
from .features import motion as _motion
from .features import nle_export as _nle_export
from .features import offline as _offline
from .features import package_export as _package_export
from .features import parakeet_asr as _parakeet
from .features import pyannote_backend as _pyannote
from .features import quality_gate as _quality_gate
from .features import ranker as _ranker
from .features import recipes as _recipes
from .features import saliency as _saliency
from .features import scene_transnet as _scene_transnet
from .features import scorer as _scorer
from .features import select as _select
from .features import subtitles as _subtitles
from .features import system_advisor as _system_advisor
from .features import transcribe as _transcribe
from .features import vlm_backbone as _vlm_backbone
from .features.audiomix import (
    AudioMix,
    AudioMixError,
)
from .features.audiomix import (
    build_loudnorm_argv as build_loudnorm_argv,
)
from .features.audiomix import (
    build_mix_argv as build_audio_mix_argv,
)
from .features.audiomix import (
    build_mix_filter as build_audio_mix_filter,
)
from .features.silencetrim import (
    SilenceTrim,
    SilenceTrimError,
    detect_silence_spans,
    keep_spans,
    parse_silence_spans,
    removed_seconds,
)
from .features.silencetrim import (
    trim_clip as trim_silence,
)
from .features.stabilize import (
    StabilizeEngine,
    StabilizeError,
    StabilizeService,
    make_unavailable_notice,
    stabilize_clip,
)
from .features.stabilize import (
    vidstab_available as stabilize_available,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable


# --------------------------------------------------------------------------- #
# subtitles namespace (generate / edit / translate / bilingual / export)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _SubtitlesFacade:
    """Stable handles onto ``features.subtitles`` (the bilingual+export surface)."""

    generate: Callable = _subtitles.generate
    generate_polished: Callable = _subtitles.generate_polished
    edit: Callable = _subtitles.edit
    translate: Callable = _subtitles.translate
    stack_bilingual: Callable = _subtitles.stack_bilingual
    stack_cue_text: Callable = _subtitles.stack_cue_text
    serialize: Callable = _subtitles.serialize
    export: Callable = _subtitles.export


# --------------------------------------------------------------------------- #
# nle namespace (EDL / CSV timeline export)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _NleFacade:
    """Stable handles onto ``features.nle_export`` (CMX3600 EDL + CSV)."""

    FPS_CHOICES: tuple[int, ...] = _nle_export.FPS_CHOICES
    FORMATS: tuple[str, ...] = _nle_export.FORMATS
    clips_to_events: Callable = _nle_export.clips_to_events
    build_edl: Callable = _nle_export.build_edl
    build_csv: Callable = _nle_export.build_csv
    seconds_to_timecode: Callable = _nle_export.seconds_to_timecode
    serialize: Callable = _nle_export.serialize
    export: Callable = _nle_export.export


# --------------------------------------------------------------------------- #
# package namespace (ZIP "package for upload")
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _PackageFacade:
    """Stable handles onto ``features.package_export`` (the upload ZIP bundle)."""

    build_suggestion: Callable = _package_export.build_suggestion
    build_manifest: Callable = _package_export.build_manifest
    slugify_tags: Callable = _package_export.slugify_tags
    package: Callable = _package_export.package


#: Module-level singletons — the public facade surface.
subtitles = _SubtitlesFacade()
nle = _NleFacade()
package = _PackageFacade()


# --------------------------------------------------------------------------- #
# offline mode (system-advanced)
# --------------------------------------------------------------------------- #
OfflineError = _offline.OfflineError
is_offline = _offline.is_offline
guard_network = _offline.guard_network
enforce_offline_env = _offline.enforce_offline_env
SETTING_OFFLINE = _offline.SETTING_OFFLINE

# --------------------------------------------------------------------------- #
# system health (system-advanced)
# --------------------------------------------------------------------------- #
Health = _health.Health
parse_ffmpeg_version = _health.parse_ffmpeg_version
ML_BACKENDS = _health.ML_BACKENDS

# --------------------------------------------------------------------------- #
# pipeline recipes (system-advanced)
# --------------------------------------------------------------------------- #
RecipeStore = _recipes.RecipeStore
Recipes = _recipes.Recipes
normalize_recipe = _recipes.normalize_recipe
resolve_refs = _recipes.resolve_refs

# --------------------------------------------------------------------------- #
# diarization (system-advanced)
# --------------------------------------------------------------------------- #
Diarize = _diarize.Diarize
diarize_transcript = _diarize.diarize_transcript
greedy_cluster = _diarize.greedy_cluster
cosine_similarity = _diarize.cosine_similarity
speaker_label = _diarize.speaker_label
DIARIZE_REQUIRED_ASSETS = _diarize.REQUIRED_ASSETS
# Phase-8: the opt-in pyannote 3.1 diarization backend (gated HF weights).
PyannoteDiarizer = _pyannote.PyannoteDiarizer
select_diarize_backend = _pyannote.select_backend_factory
selected_diarize_backend = _pyannote.selected_backend_name

# --------------------------------------------------------------------------- #
# ASR engine selection (Phase-8 WU7) — whisper (default) | parakeet
# --------------------------------------------------------------------------- #
transcribe_file = _transcribe.transcribe_file
transcribe_with_engine = _transcribe.transcribe_with_engine
selected_asr_engine = _transcribe.selected_asr_engine
ASR_ENGINES = _transcribe.ASR_ENGINES
parakeet_transcribe = _parakeet.transcribe_file
ParakeetLoader = _parakeet.ParakeetLoader

# --------------------------------------------------------------------------- #
# word-timing alignment (Phase-8 WU6 — ctc-forced-aligner)
# --------------------------------------------------------------------------- #
align_words = _ctc_align.align_words

# --------------------------------------------------------------------------- #
# caption polish (Phase-8 WU9 — Netflix CPS/CPL + punct/casing/emphasis/profanity)
# --------------------------------------------------------------------------- #
polish_cues = _caption_polish.polish_cues
CAPTION_MAX_CPS = _caption_polish.MAX_CPS
CAPTION_MAX_CPL = _caption_polish.MAX_CPL

# --------------------------------------------------------------------------- #
# unified tri-modal scorer (Phase-8 WU5 — select.select_unified + scorer fusion)
# --------------------------------------------------------------------------- #
select_unified = _select.select_unified
window_interest_curve = _scorer.window_interest_curve
clip_signal_map = _scorer.clip_signal_map


# --------------------------------------------------------------------------- #
# Phase-8 signals namespace (the Wave-1 signal-compute + selection primitives)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _SignalsFacade:
    """Stable handles onto the Wave-1 signal modules + the selection primitives.

    Groups the per-modality ``compute_*`` entry points (motion / saliency / audio /
    scene-cut / SigLIP-2 backbone), the optional DOVER quality gate, and the
    Tier-0 diversity + learned-ranker primitives under one short handle so callers
    consume them from the facade instead of reaching into each feature module.
    """

    compute_motion_signals: Callable = _motion.compute_motion_signals
    compute_saliency_signals: Callable = _saliency.compute_saliency_signals
    compute_audio_signals: Callable = _audio_saliency.compute_audio_signals
    compute_scene_signals: Callable = _scene_transnet.compute_scene_signals
    compute_backbone_signals: Callable = _vlm_backbone.compute_backbone_signals
    compute_quality_scores: Callable = _quality_gate.compute_quality_scores
    apply_quality_gate: Callable = _quality_gate.apply_quality_gate
    dedupe_candidates: Callable = _diversity.dedupe_candidates
    rank: Callable = _ranker.rank
    train_ranker: Callable = _ranker.train_ranker


#: Module-level singleton — the Phase-8 signal/selection facade surface.
signals = _SignalsFacade()


# --------------------------------------------------------------------------- #
# system advisor (Phase-8 — capability/preset advisor behind system.advisor)
# --------------------------------------------------------------------------- #
advise_for_hardware = _system_advisor.advise_for_hardware
HardwareProbe = _system_advisor.HardwareProbe
AdvisorReport = _system_advisor.AdvisorReport


__all__ = [
    # --- namespaced facades (captions-export group) ---
    "nle",
    "package",
    "subtitles",
    # --- stabilization (audio-stabilize group) ---
    "StabilizeEngine",
    "StabilizeError",
    "StabilizeService",
    "make_unavailable_notice",
    "stabilize_available",
    "stabilize_clip",
    # --- audio mix / loudnorm ---
    "AudioMix",
    "AudioMixError",
    "build_audio_mix_argv",
    "build_audio_mix_filter",
    "build_loudnorm_argv",
    # --- silence trim ---
    "SilenceTrim",
    "SilenceTrimError",
    "detect_silence_spans",
    "keep_spans",
    "parse_silence_spans",
    "removed_seconds",
    "trim_silence",
    # --- offline mode (system-advanced group) ---
    "OfflineError",
    "SETTING_OFFLINE",
    "enforce_offline_env",
    "guard_network",
    "is_offline",
    # --- system health (system-advanced) ---
    "Health",
    "ML_BACKENDS",
    "parse_ffmpeg_version",
    # --- pipeline recipes (system-advanced) ---
    "RecipeStore",
    "Recipes",
    "normalize_recipe",
    "resolve_refs",
    # --- diarization (system-advanced) ---
    "DIARIZE_REQUIRED_ASSETS",
    "Diarize",
    "PyannoteDiarizer",
    "cosine_similarity",
    "diarize_transcript",
    "greedy_cluster",
    "select_diarize_backend",
    "selected_diarize_backend",
    "speaker_label",
    # --- ASR engine selection (Phase-8 WU7) ---
    "ASR_ENGINES",
    "ParakeetLoader",
    "parakeet_transcribe",
    "selected_asr_engine",
    "transcribe_file",
    "transcribe_with_engine",
    # --- word-timing alignment (Phase-8 WU6) ---
    "align_words",
    # --- caption polish (Phase-8 WU9) ---
    "CAPTION_MAX_CPL",
    "CAPTION_MAX_CPS",
    "polish_cues",
    # --- unified tri-modal scorer (Phase-8 WU5) ---
    "clip_signal_map",
    "select_unified",
    "window_interest_curve",
    # --- Phase-8 signal/selection facade + system advisor ---
    "AdvisorReport",
    "HardwareProbe",
    "advise_for_hardware",
    "signals",
]
