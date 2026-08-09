"""TTS voiceover/dub feature package (CONTRACTS.md A2/A4, T2).

Modules:

  * :mod:`.engine`      — the A4 ``TtsEngine`` ABC + shared WAV helpers
  * :mod:`.kokoro`      — default local engine (kokoro-onnx / onnxruntime)
  * :mod:`.edgetts`     — hosted engine (edge-tts), labeled ONLINE
  * :mod:`.chatterbox`  — voice-clone engine (isolated torch env, subprocess)
  * :mod:`.align`       — the FROZEN per-cue alignment recipe (±15% atempo)
  * :mod:`.dub`         — the batched dub pipeline + ``tts.dub.start``
  * :mod:`.voices`      — voice catalog + sample store (``tts.voices`` /
    ``tts.sample.add``)
  * :mod:`.lipsync`     — re-lip the mouth to a finished dub
    (``tts.lipsync.start``); OFF unless ``lipSyncEnabled`` is ``True``

:func:`register` is the composition entry the WIRING agent calls from
``handlers.register_all`` (mirroring the other feature modules). It builds
the engine factories, the voice store and the dub service, and registers the
three frozen A2 methods. Importing this package stays light: no onnxruntime
/ edge-tts / torch import happens until a job actually runs (A6 lesson 1 —
the natives the wiring agent must pre-import are listed in docs/wiring/WIRING-T2.md).

``tts.lipsync.start`` is registered UNCONDITIONALLY and refuses at CALL time
when the flag is off. Registering it conditionally would make the method's
existence depend on the settings snapshot taken at composition time, so a user
toggling the setting would need a restart AND the UI could not tell "disabled"
from "this build has no lip-sync". A method that answers "disabled, here is how
to enable it" is strictly more honest than one that answers "unknown method".
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from ... import protocol
from ...util import get_logger
from .chatterbox import ChatterboxEngine
from .dub import DubService, Translator
from .edgetts import EdgeTtsEngine
from .engine import TtsEngine, TtsError
from .kokoro import KokoroEngine
from .lipsync import BackendFactory, ConfidenceProbe, FaceBoxesProbe, LipSyncService
from .voices import VoiceStore, make_sample_add_handler, make_voices_handler

log = get_logger("media_studio.tts")

# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]


def default_engine_factories(
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    assets_root: str | None = None,
) -> dict[str, Callable[[], TtsEngine]]:
    """The A4 engine registry: exactly kokoro / edgetts / chatterbox.

    Factories (not instances) so no backend is touched until a dub job runs.
    """
    root = str(assets_root) if assets_root is not None else None
    return {
        "kokoro": lambda: KokoroEngine(assets_root=root),
        "edgetts": lambda: EdgeTtsEngine(settings_provider=settings_provider),
        "chatterbox": lambda: ChatterboxEngine(assets_root=root),
    }


def register(
    *,
    resolver: Resolver,
    load_track: Callable[[str, str], dict[str, Any]],
    audio_tracks: Any,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    translator_factory: Callable[[], Translator] | None = None,
    engines: dict[str, Callable[[], TtsEngine]] | None = None,
    voice_store: VoiceStore | None = None,
    samples_dir: str | os.PathLike | None = None,
    media_duration: Callable[[str], float] | None = None,
    out_dir: str | None = None,
    lipsync_backend_factory: BackendFactory | None = None,
    lipsync_confidence_probe: ConfidenceProbe | None = None,
    lipsync_face_boxes_probe: FaceBoxesProbe | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> DubService:
    """Register ``tts.voices`` / ``tts.sample.add`` / ``tts.dub.start`` (A2) +
    ``tts.lipsync.start`` (WU-B1).

    Called by the wiring agent from ``handlers.register_all`` with:

    * ``resolver`` — videoId -> media path (``Services._resolve_video_path``);
    * ``load_track`` — (videoId, trackId) -> the §3 SubtitleTrack from the
      video's project manifest;
    * ``audio_tracks`` — the :class:`..tracks_audio.AudioTracksService`
      returned by that module's own ``register()`` (mux + persistence);
    * ``translator_factory`` — the models.translation (T3) seam adapter.

    Tests pass fakes + a fake ``register_fn``. Returns the DubService.
    """
    store = voice_store or VoiceStore(samples_dir)
    factories = engines or default_engine_factories(settings_provider)
    # The voices catalog needs INSTANCES for their static lists; building the
    # three engines is cheap (no backend import happens in a constructor).
    catalog_engines = [factory() for factory in factories.values()]
    service = DubService(
        resolver=resolver,
        load_track=load_track,
        engines=factories,
        voice_store=store,
        audio_tracks=audio_tracks,
        translator_factory=translator_factory,
        settings_provider=settings_provider,
        media_duration=media_duration,
        out_dir=out_dir,
    )

    # WU-B1: lip-sync consumes a FINISHED dub AudioTrack, so its audio-track
    # loader is derived from the same service the dub muxes into, and its
    # cloned-voice consent lookup from the same VoiceStore the dub voiced from.
    # No new persistence surface — the gate reads what already exists.
    def load_audio_track(video_id: str, track_id: str) -> dict[str, Any] | None:
        rows = audio_tracks.list({"videoId": video_id}, None).get("audioTracks", [])
        return next((dict(row) for row in rows if row.get("id") == track_id), None)

    lipsync = LipSyncService(
        resolver=resolver,
        load_audio_track=load_audio_track,
        get_sample=store.get,
        backend_factory=lipsync_backend_factory,
        settings_provider=settings_provider,
        confidence_probe=lipsync_confidence_probe,
        # NOT wired by any caller yet, so a real relip fails LOUD naming S3FD
        # rather than letting the engine detect faces with an unlicensed weight.
        face_boxes_probe=lipsync_face_boxes_probe,
        out_dir=out_dir,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("tts.voices", make_voices_handler(catalog_engines, store))
    reg("tts.sample.add", make_sample_add_handler(store))
    reg("tts.dub.start", service.dub_start)
    reg("tts.lipsync.start", lipsync.lipsync_start)
    log.info("registered tts.voices / tts.sample.add / tts.dub.start / tts.lipsync.start")
    return service


__all__ = [
    "BackendFactory",
    "ChatterboxEngine",
    "ConfidenceProbe",
    "DubService",
    "EdgeTtsEngine",
    "FaceBoxesProbe",
    "KokoroEngine",
    "LipSyncService",
    "Translator",
    "TtsEngine",
    "TtsError",
    "VoiceStore",
    "default_engine_factories",
    "register",
]
