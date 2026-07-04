"""F4b regression guard: the public RPC surface is byte-identical after the split.

The former monolithic ``handlers.py`` was split into a feature-grouped
``media_studio.handlers`` package wired by the same ``register_all`` composition
root. This test freezes the EXACT set of method names ``register_all`` registers
so the split (and any future refactor) cannot silently add, drop, or rename a
wire method. It captures the names via a fake registrar — no real
``protocol.METHODS`` mutation, no provider/LLM/socket.
"""

from __future__ import annotations

from pathlib import Path

from media_studio import handlers
from media_studio.handlers import Services

# The frozen v1.1.0 RPC surface (every method register_all wires onto the
# registry). Sorted; update DELIBERATELY when a method is intentionally added.
FROZEN_RPC_SURFACE: frozenset[str] = frozenset(
    {
        "ai.planJob",
        "asr.engines",
        "assets.cancel",
        "assets.ensure",
        "assets.list",
        "audiomix.merge",
        "audiomix.normalize",
        "batch.cancel",
        "batch.create",
        "batch.delete",
        "batch.list",
        "batch.resume",
        "batch.start",
        "batch.status",
        "captions.cues",
        "convert.batch",
        "convert.start",
        "diarize.rename",
        "diarize.start",
        "director.apply",
        "director.evaluate",
        "director.plan",
        "director.previewCost",
        "director.undo",
        "exportPresets.delete",
        "exportPresets.list",
        "exportPresets.reset",
        "exportPresets.save",
        "feedback.record",
        "feedback.stats",
        "index.build",
        "index.search",
        "index.status",
        "library.add",
        "library.lineage",
        "library.list",
        "library.pinHash",
        "library.regenerate",
        "library.relink",
        "library.remove",
        "library.reveal",
        "library.thumbnail",
        "media.playable",
        "media.proxy.start",
        "models.overview",
        "models.resolveRoute",
        "models.runners",
        "models.setRoutingPolicy",
        "nle.export",
        "package.export",
        "paths.describe",
        "phase8.select",
        "phase8.signals",
        "project.consolidate",
        "project.open",
        "project.save",
        "providers.applyPreset",
        "providers.catalog",
        "providers.firstRun",
        "providers.list",
        "providers.openrouterUsage",
        "providers.remove",
        "providers.revealKey",
        "providers.setConsent",
        "providers.setFunctionModel",
        "providers.spend",
        "providers.testKey",
        "providers.upsert",
        "providers.usage",
        "providers.usageAvailability",
        "readiness.summary",
        "recipes.delete",
        "recipes.list",
        "recipes.run",
        "recipes.save",
        "refine.apply",
        "refine.preview",
        "reframe.applyOverrides",
        "reframe.eval",
        "reframe.shotPlan",
        "savePresets.apply",
        "savePresets.list",
        "savePresets.remove",
        "savePresets.upsert",
        "settings.get",
        "settings.set",
        "shortmaker.export",
        "shortmaker.select",
        "shorts.delete",
        "shorts.list",
        "shorts.reexport",
        "shorts.thumbnail",
        "silence.trim",
        "stabilize.run",
        "subtitles.edit",
        "subtitles.export",
        "subtitles.generate",
        "subtitles.translate",
        "system.advisor",
        "system.health",
        "system.probe",
        "system.recommend",
        "system.selfTest",
        "templates.apply",
        "templates.delete",
        "templates.list",
        "templates.save",
        "thumbnail.select",
        "timeline.peaks",
        "tracks.add",
        "tracks.audio.list",
        "tracks.audio.mux",
        "tracks.audio.replace",
        "tracks.audio.strip",
        "tracks.burn",
        "tracks.list",
        "tracks.relabel",
        "tracks.remove",
        "tracks.rename",
        "tracks.strip",
        "transcribe.start",
        "tts.dub.start",
        "tts.sample.add",
        "tts.voices",
    }
)


def _registered_names(tmp_path: Path) -> list[str]:
    names: list[str] = []
    svc = Services(data_dir=tmp_path / "data")
    handlers.register_all(services=svc, register=lambda name, handler: names.append(name))
    return names


def test_rpc_surface_is_byte_identical(tmp_path: Path) -> None:
    """register_all wires EXACTLY the frozen method set — nothing added or dropped."""
    assert set(_registered_names(tmp_path)) == FROZEN_RPC_SURFACE


def test_rpc_surface_has_no_duplicate_registrations(tmp_path: Path) -> None:
    """Each method is registered exactly once (a typo/double-wire fails loudly)."""
    names = _registered_names(tmp_path)
    assert len(names) == len(set(names))


def test_handlers_package_reexports_public_surface() -> None:
    """The package __init__ keeps the former monolith's public names importable."""
    assert handlers.Services is Services
    assert callable(handlers.register_all)
    # Private helpers a few tests import directly from media_studio.handlers.
    for name in ("_coerce_tier", "_js_number", "_evenly_spaced", "_require_number", "log"):
        assert hasattr(handlers, name)
