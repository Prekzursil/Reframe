"""Stable, transport-agnostic ENGINE facade for the system-advanced features.

The feature modules under ``media_studio/features`` ship pure functions + thin
RPC services. This facade is the **stable seam** other code (and the Electron
side, future CLIs, tests) can depend on WITHOUT reaching into a feature module's
internals or the JSON-RPC wire shape. It re-exports each feature's pure core
under a small, named surface so a caller never imports a heavy backend.

Everything here is import-light: this module imports only the pure-logic halves
(no speechbrain / faster-whisper / torch / network). The heavy paths stay behind
the same loader seams the feature modules use.

Surface (this group — "system-advanced"):

  * OFFLINE     ``is_offline`` · ``guard_network`` · ``enforce_offline_env``
  * HEALTH      ``Health`` (build a report instance) · ``parse_ffmpeg_version``
  * RECIPES     ``RecipeStore`` · ``normalize_recipe`` · ``resolve_refs``
  * DIARIZE     ``diarize_transcript`` · ``greedy_cluster`` · ``speaker_label``
                · ``cosine_similarity`` · ``REQUIRED_ASSETS``

These names are the contract the serial integrator can rely on; the underlying
modules may move/refactor as long as this facade keeps them stable.
"""

from __future__ import annotations

from .features import diarize as _diarize
from .features import health as _health
from .features import offline as _offline
from .features import recipes as _recipes

# -- offline mode ----------------------------------------------------------- #
OfflineError = _offline.OfflineError
is_offline = _offline.is_offline
guard_network = _offline.guard_network
enforce_offline_env = _offline.enforce_offline_env
SETTING_OFFLINE = _offline.SETTING_OFFLINE

# -- system health ---------------------------------------------------------- #
Health = _health.Health
parse_ffmpeg_version = _health.parse_ffmpeg_version
ML_BACKENDS = _health.ML_BACKENDS

# -- pipeline recipes ------------------------------------------------------- #
RecipeStore = _recipes.RecipeStore
Recipes = _recipes.Recipes
normalize_recipe = _recipes.normalize_recipe
resolve_refs = _recipes.resolve_refs

# -- diarization ------------------------------------------------------------ #
Diarize = _diarize.Diarize
diarize_transcript = _diarize.diarize_transcript
greedy_cluster = _diarize.greedy_cluster
cosine_similarity = _diarize.cosine_similarity
speaker_label = _diarize.speaker_label
DIARIZE_REQUIRED_ASSETS = _diarize.REQUIRED_ASSETS


__all__ = [
    "DIARIZE_REQUIRED_ASSETS",
    "ML_BACKENDS",
    "SETTING_OFFLINE",
    "Diarize",
    "Health",
    "OfflineError",
    "RecipeStore",
    "Recipes",
    "cosine_similarity",
    "diarize_transcript",
    "enforce_offline_env",
    "greedy_cluster",
    "guard_network",
    "is_offline",
    "normalize_recipe",
    "parse_ffmpeg_version",
    "resolve_refs",
    "speaker_label",
]
