"""Export-preset catalog (the repurpose bundle's WU1 store).

An *export preset* is a server-persisted, editable platform target — the
durable, multi-source promotion of the renderer-only ``PLATFORM_PRESETS`` (the
TikTok / Reels / Shorts buttons in ``shortMakerPresets.ts``). Moving it
server-side lets templates and batch runs reference presets by id and lets the
catalog be edited without a renderer rebuild.

Wire shape (frozen — field names identical both sides)::

    ExportPreset = {
        id, label, aspect,
        minSec, maxSec,            # clamped into the §5 hard 20-60 s window
        count,                     # >= 1
        captionStyle,              # validated against the sidecar caption catalog
        reframeEngine,             # auto | verthor | claudeshorts
    }

Storage mirrors :class:`recipes.RecipeStore` exactly: one JSON document under the
data root, written atomically (temp file + ``os.replace``) so a crash mid-write
can never truncate the catalog. The catalog is **seeded** on first read with the
three vertical platforms (all 9:16) so day-one behavior matches the current UI;
``reset`` restores those seeds.

Pure logic + filesystem only — no heavy-ML / network / provider imports. The
``captionStyle`` id-guard reuses the sidecar's authoritative caption-style set
(``caption_remotion.STYLES`` plus the two libass sentinels ``libass`` / ``none``)
rather than re-listing it, so the catalog can never drift from what the
CaptionEngine actually renders.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import clamp, get_logger
from . import caption_remotion

log = get_logger("media_studio.features.export_presets")

ExportPreset = dict[str, Any]

#: The §5 hard clip window (mirrors ``select._resolve_window`` / the renderer's
#: ``MIN_CLIP_SEC`` / ``MAX_CLIP_SEC``): a preset's saved window is clamped here so
#: the catalog can never promise a duration the pipeline would silently correct.
MIN_CLIP_SEC = 20
MAX_CLIP_SEC = 60

#: Allowed ``captionStyle`` ids — the authoritative sidecar caption catalog: every
#: remotion template plus the two libass sentinels. Single-sourced from
#: :data:`caption_remotion.STYLES` so the guard tracks the real renderers.
CAPTION_STYLES: frozenset[str] = frozenset({"libass", "none", *caption_remotion.STYLES})

#: Allowed ``reframeEngine`` ids (A4 engines + the "auto" selector).
REFRAME_ENGINES: frozenset[str] = frozenset({"auto", "verthor", "claudeshorts"})

#: Default reframe engine when a preset omits one (verthor with fallback).
DEFAULT_REFRAME_ENGINE = "auto"


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"preset.{key} (non-empty str) is required")
    return value.strip()


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    # bool is an int subclass; reject it explicitly so True/False can't pose as a count.
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid(f"preset.{key} (int) is required")
    return value


# --------------------------------------------------------------------------- #
# pure: preset shaping + window clamp + id guards
# --------------------------------------------------------------------------- #
def normalize_preset(raw: Any) -> ExportPreset:
    """Validate + normalize an export-preset payload into the frozen wire shape.

    Clamps the ``minSec``/``maxSec`` window into the hard ``[20, 60]`` range (and
    never lets it invert), floors ``count`` at 1, and rejects an unknown
    ``captionStyle`` / ``reframeEngine`` with a fail-loud ``RpcError`` so a bad
    save can never persist a half-typed or unrenderable record. A missing ``id``
    is generated.
    """
    if not isinstance(raw, dict):
        raise _invalid("preset must be an object")

    label = _require_str(raw, "label")
    aspect = _require_str(raw, "aspect")
    min_sec = _require_int(raw, "minSec")
    max_sec = _require_int(raw, "maxSec")
    count = _require_int(raw, "count")

    caption_style = _require_str(raw, "captionStyle")
    if caption_style not in CAPTION_STYLES:
        raise _invalid(f"unknown captionStyle: {caption_style!r}")

    reframe_engine = raw.get("reframeEngine")
    if reframe_engine is None:
        reframe_engine = DEFAULT_REFRAME_ENGINE
    elif not isinstance(reframe_engine, str) or reframe_engine not in REFRAME_ENGINES:
        raise _invalid(f"unknown reframeEngine: {reframe_engine!r}")

    # Clamp the window into [20, 60], then hold minSec at-or-below the clamped
    # maxSec so the window can never invert (mirrors applyPreset's CONTRACT-NOTE).
    clamped_max = int(clamp(max_sec, MIN_CLIP_SEC, MAX_CLIP_SEC))
    clamped_min = int(clamp(min_sec, MIN_CLIP_SEC, clamped_max))

    preset_id = raw.get("id")
    if not isinstance(preset_id, str) or not preset_id:
        preset_id = uuid.uuid4().hex[:12]

    return {
        "id": preset_id,
        "label": label,
        "aspect": aspect,
        "minSec": clamped_min,
        "maxSec": clamped_max,
        "count": max(1, count),
        "captionStyle": caption_style,
        "reframeEngine": reframe_engine,
    }


def seed_presets() -> list[ExportPreset]:
    """The day-one catalog: the three vertical platforms (all 9:16).

    Mirrors the renderer's frozen ``PLATFORM_PRESETS`` (TikTok 5 / Reels 3 /
    Shorts 8). ``maxSec`` is the in-window sweet-spot per platform; Reels' 90 s
    documented length is clamped to the enforceable 60 s, identical to the
    renderer + ``select._resolve_window``.
    """
    return [
        normalize_preset(
            {
                "id": "tiktok",
                "label": "TikTok",
                "aspect": "9:16",
                "minSec": 20,
                "maxSec": 60,
                "count": 5,
                "captionStyle": "libass",
            }
        ),
        normalize_preset(
            {
                "id": "reels",
                "label": "Reels",
                "aspect": "9:16",
                "minSec": 20,
                "maxSec": 90,
                "count": 3,
                "captionStyle": "libass",
            }
        ),
        normalize_preset(
            {
                "id": "shorts",
                "label": "Shorts",
                "aspect": "9:16",
                "minSec": 20,
                "maxSec": 60,
                "count": 8,
                "captionStyle": "libass",
            }
        ),
    ]


# --------------------------------------------------------------------------- #
# storage (JSON document under the data root; mirrors RecipeStore)
# --------------------------------------------------------------------------- #
class PresetStore:
    """A JSON-backed export-preset catalog (atomic temp+rename writes).

    Self-seeding: an empty / missing / corrupt file is recovered to the three
    vertical seeds on read (and the recovered catalog is persisted), so the
    catalog is never empty and a poisoned file can't surface as a blank UI.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def _read_raw(self) -> list[ExportPreset] | None:
        """Return the on-disk catalog, or ``None`` if absent/corrupt/non-list."""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("export-presets file unreadable (%s); reseeding", exc)
            return None
        if not isinstance(data, list):
            return None
        return [p for p in data if isinstance(p, dict)]

    def _read(self) -> list[ExportPreset]:
        """Read the catalog, seeding (and persisting) the defaults when empty."""
        existing = self._read_raw()
        if existing is None:
            seeded = seed_presets()
            self._write(seeded)
            return seeded
        return existing

    def _write(self, presets: list[ExportPreset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(presets, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[ExportPreset]:
        return self._read()

    def save(self, preset: ExportPreset) -> ExportPreset:
        """Upsert ``preset`` by id (replace same-id, else append). Returns it.

        The preset is normalized first (window clamp + id guards), so an invalid
        ``captionStyle`` raises BEFORE any write — the catalog stays intact.
        """
        normalized = normalize_preset(preset)
        presets = self._read()
        replaced = False
        out: list[ExportPreset] = []
        for existing in presets:
            if existing.get("id") == normalized["id"]:
                out.append(normalized)
                replaced = True
            else:
                out.append(existing)
        if not replaced:
            out.append(normalized)
        self._write(out)
        return normalized

    def delete(self, preset_id: str) -> bool:
        presets = self._read()
        remaining = [p for p in presets if p.get("id") != preset_id]
        if len(remaining) == len(presets):
            return False
        self._write(remaining)
        return True

    def reset(self) -> list[ExportPreset]:
        """Restore the three vertical seeds, overwriting any edits. Returns them."""
        seeded = seed_presets()
        self._write(seeded)
        return seeded


# --------------------------------------------------------------------------- #
# RPC service (WU2): direct-return CRUD over the catalog (mirrors Recipes)
# --------------------------------------------------------------------------- #
class ExportPresets:
    """The ``exportPresets.*`` handler group — thin direct-return CRUD.

    Each method validates the wire params and delegates to a :class:`PresetStore`;
    no jobs, no notifications (storage-only), mirroring ``recipes.Recipes`` CRUD.
    The ``ctx`` is part of the handler signature for registry uniformity but is
    unused here (the catalog never emits progress).
    """

    def __init__(self, store: PresetStore) -> None:
        self.store = store

    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``exportPresets.list()`` -> ``{presets:[ExportPreset]}`` (direct-return)."""
        return {"presets": self.store.list()}

    def save(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``exportPresets.save({preset})`` -> ``{preset}`` (direct-return; upsert).

        The preset is normalized (window clamp + id guards) before any write, so a
        bad ``captionStyle`` raises and the catalog stays intact.
        """
        raw = params.get("preset")
        if not isinstance(raw, dict):
            raise _invalid("preset (object) is required")
        return {"preset": self.store.save(raw)}

    def delete(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``exportPresets.delete({id})`` -> ``{ok}`` (direct-return)."""
        preset_id = _require_str(params, "id")
        return {"ok": self.store.delete(preset_id)}

    def reset(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``exportPresets.reset()`` -> ``{presets}`` (restore the three seeds)."""
        return {"presets": self.store.reset()}


def register(
    *,
    path: str | os.PathLike[str],
    register_fn: Callable[[str, Any], None] | None = None,
) -> ExportPresets:
    """Create an :class:`ExportPresets` over ``path`` and register the four methods.

    ``register_fn`` defaults to :func:`protocol.register`; tests inject a fake
    registrar + a tmp ``path``. Returns the service so the caller can hold it
    (mirrors :func:`recipes.register`).
    """
    service = ExportPresets(PresetStore(path))
    reg = register_fn if register_fn is not None else protocol.register
    reg("exportPresets.list", service.list)
    reg("exportPresets.save", service.save)
    reg("exportPresets.delete", service.delete)
    reg("exportPresets.reset", service.reset)
    return service
