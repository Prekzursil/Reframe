"""media_studio.engine — the stable, transport-agnostic feature facade.

This is the ONE import surface callers (handlers, scripts, future SDK consumers)
use to reach the engine features WITHOUT depending on each feature module's
internal layout. Each feature lives in its own ``features/<name>.py`` (the
transport-agnostic engine); this facade re-exports the stable, named entry points
so a refactor inside a feature module never breaks a caller.

Stable entry points (NET-NEW — the "audio-stabilize" group):

  * **Stabilization** (camera-shake, ffmpeg vidstab 2-pass):
      ``stabilize_clip(in, out, *, settings, on_notice) -> out|in``  (pipeline pre-step)
      ``StabilizeEngine`` / ``stabilize_available(settings) -> bool``  (libvidstab probe)

  * **A/V merge + auto-duck + EBU R128 loudnorm**:
      ``build_audio_mix_argv(...)`` / ``AudioMix``  (mix a bed under the clip)
      ``build_loudnorm_argv(...)``                  (normalize-only)

  * **Silence-trim / dead-air removal**:
      ``trim_silence(in, out, *, settings) -> (out|in, removedSec)``  (pipeline pre-step)
      ``detect_silence_spans(...)`` / ``keep_spans(...)``             (pure helpers)

Nothing heavy is imported at facade load: the feature modules already keep ffmpeg
/ heavy deps behind lazy imports + injectable seams, so importing this facade is
import-light and side-effect-free.
"""

from __future__ import annotations

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

__all__ = [
    # --- stabilization ---
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
]
