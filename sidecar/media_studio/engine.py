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

from .features import diarize as _diarize
from .features import health as _health
from .features import nle_export as _nle_export
from .features import offline as _offline
from .features import package_export as _package_export
from .features import recipes as _recipes
from .features import subtitles as _subtitles
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
    "cosine_similarity",
    "diarize_transcript",
    "greedy_cluster",
    "speaker_label",
]
