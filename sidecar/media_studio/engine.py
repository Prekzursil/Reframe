"""Engine facade — one stable, transport-agnostic import surface for features.

The feature modules under ``media_studio/features/`` are the real implementations;
this module is a thin *facade* that re-exports their stable entry points under
short, namespaced handles so callers (other features, scripts, future RPC
wiring) depend on ONE place instead of reaching into individual feature modules.

It is deliberately import-light: only pure-logic feature modules are imported at
module load (no faster-whisper / scenedetect / provider), matching the
``handlers.py`` discipline. Heavy features stay behind their own lazy seams.

Each facade namespace is a small ``@dataclass(frozen=True)`` of callables bound to
the underlying feature functions, exposed as a module-level singleton::

    from media_studio import engine
    track = engine.subtitles.stack_bilingual(orig, translated)
    path  = engine.nle.export(clips, "out.edl", fmt="edl", fps=30)
    res   = engine.package.package(clip, "bundle.zip", meta=meta)

Adding a feature to the facade = add its module import + a frozen namespace +
re-export. No behavior lives here; it is purely a wiring/discoverability layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .features import nle_export as _nle_export
from .features import package_export as _package_export
from .features import subtitles as _subtitles

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


__all__ = ["nle", "package", "subtitles"]
