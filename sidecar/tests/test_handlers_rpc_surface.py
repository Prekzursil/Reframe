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
        "assets.plan",
        "audiomix.merge",
        "audiomix.normalize",
        "batch.cancel",
        "batch.create",
        "batch.delete",
        "batch.list",
        "batch.plan",
        "batch.resume",
        "batch.start",
        "batch.status",
        # v1.5 flagship #3 (auto-b-roll): local asset retrieval + compositing.
        # None of these may ever gain a key-injection prefix — they are
        # local-only and never call a provider (features/broll_ops.py).
        #
        # v1.5 DELIBERATE addition (design BR1): `broll.addAsset` / `broll.assets` /
        # `broll.removeAsset` — the b-roll asset REGISTRY. Named explicitly here
        # because adding an RPC method must be a conscious act: the four engine
        # methods below shipped with NO way to register an asset, so the entire
        # library was a scan of one `brollDir` setting and nothing in the app could
        # put a specific file into it. These three are Library CRUD over
        # `role='broll'` entity rows (handlers/library_ops.py) — local-only like the
        # rest of the family, no provider, no model, no network. Verified this gate
        # is not vacuous: registering them with the set unchanged failed
        # test_rpc_surface_is_byte_identical first.
        "broll.addAsset",
        "broll.apply",
        "broll.assets",
        "broll.index",
        "broll.removeAsset",
        "broll.status",
        "broll.suggest",
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
        # C15 eye-contact correction. gaze.run is LIKENESS-GATED (it refuses
        # without an attestation); gaze.probe reports whether the shared YuNet
        # asset is installed so the UI can disable the control up front.
        "gaze.probe",
        "gaze.run",
        "index.build",
        "index.plan",
        "index.search",
        "index.status",
        "library.add",
        "library.keepCopy",
        "library.lineage",
        "library.list",
        "library.managedClear",
        "library.managedEvict",
        "library.managedStatus",
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
        "reframe.shotPlanFor",
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
        # C14 social publish/schedule: the capability matrix + the honest
        # platform-vs-local schedule preview + publish-queue CRUD. Storage and pure
        # decisions only — no token ever reaches this side at rest.
        "social.cancel",
        "social.capabilities",
        "social.enqueue",
        "social.plan",
        "social.queue",
        # The user-driven door onto the already-wired `retime` engine: before it
        # the ONLY way to change playback speed was an LLM-planned Director op.
        "speed.retime",
        "stabilize.run",
        "subtitles.edit",
        "subtitles.export",
        "subtitles.generate",
        # v1.5 DELIBERATE addition (captions audit section 5.1): the hand-corrected
        # SRT/VTT/ASS import. Verified this gate is not vacuous — registering the
        # method with the set unchanged failed test_rpc_surface_is_byte_identical.
        "subtitles.import",
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
        "tracks.video.addClip",
        "tracks.video.addLane",
        "tracks.video.list",
        "tracks.video.moveClip",
        "tracks.video.removeClip",
        "tracks.video.removeLane",
        "tracks.video.render",
        "tracks.video.splitClip",
        "tracks.video.trimClip",
        "transcribe.start",
        # v1.5 flagship #2 — transcript-native editing (features/transcript_edit.py).
        "transcript.applyEdit",
        "transcript.get",
        "transcript.previewEdit",
        "transcript.undoEdit",
        "tts.dub.start",
        # WU-B1: registered unconditionally and refused at CALL time when the
        # lipSyncEnabled flag is off, so the frozen surface does not depend on a
        # settings snapshot taken at composition time.
        "tts.lipsync.start",
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
