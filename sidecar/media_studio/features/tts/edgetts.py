"""Edge TTS engine — the HOSTED engine, labeled ONLINE (CONTRACTS.md A4, T2).

Wraps the ``edge-tts`` package (Microsoft Edge's neural voices). The library
is imported **lazily inside synth** — module import stays network- and
dependency-free, and the network is touched only at runtime when the user
explicitly picked this engine (its UI label carries ONLINE).

edge-tts emits MP3; the engine converts to WAV with one ffmpeg pass through
the injectable ``run`` seam (:func:`media_studio.ffmpeg.run` — stderr drained
on a thread per A6 lesson 2, argv lists per lesson 4).

A6 lesson 1 note for the wiring agent: ``edge-tts`` pulls in **aiohttp**,
whose http parser is a native C-extension — add ``"aiohttp"`` to
``__main__._preimport_native_modules`` (guarded; absence fine). See
WIRING-T2.md.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ... import ffmpeg
from ...util import clamp, get_logger
from .engine import Cue, TtsEngine, TtsError, Voice

log = get_logger("media_studio.tts.edgetts")

# Factory seam: (text, voice, rate_str) -> a Communicate-like object exposing
# ``async save(path)``. Tests inject a fake; the default lazily imports edge_tts.
CommunicateFactory = Callable[[str, str, str], Any]
RunFn = Callable[..., int]

#: edge-tts accepts rate offsets like "+15%" / "-10%"; keep asks sane.
RATE_PCT_MIN = -50
RATE_PCT_MAX = 50

# CONTRACT-NOTE: A2 freezes only the voice row shape. The full catalog needs a
# network call (edge_tts.list_voices); this built-in subset keeps `tts.voices`
# instant + offline. Voice ids are the service's ShortNames.
DEFAULT_VOICES: list[Voice] = [
    {"id": "en-US-AriaNeural", "engine": "edgetts", "lang": "en-US", "name": "Aria (US female) — ONLINE"},
    {"id": "en-US-GuyNeural", "engine": "edgetts", "lang": "en-US", "name": "Guy (US male) — ONLINE"},
    {"id": "en-US-JennyNeural", "engine": "edgetts", "lang": "en-US", "name": "Jenny (US female) — ONLINE"},
    {"id": "en-GB-SoniaNeural", "engine": "edgetts", "lang": "en-GB", "name": "Sonia (UK female) — ONLINE"},
    {"id": "en-GB-RyanNeural", "engine": "edgetts", "lang": "en-GB", "name": "Ryan (UK male) — ONLINE"},
    {"id": "de-DE-KatjaNeural", "engine": "edgetts", "lang": "de-DE", "name": "Katja (German female) — ONLINE"},
    {"id": "fr-FR-DeniseNeural", "engine": "edgetts", "lang": "fr-FR", "name": "Denise (French female) — ONLINE"},
    {"id": "es-ES-ElviraNeural", "engine": "edgetts", "lang": "es-ES", "name": "Elvira (Spanish female) — ONLINE"},
    {"id": "ro-RO-AlinaNeural", "engine": "edgetts", "lang": "ro-RO", "name": "Alina (Romanian female) — ONLINE"},
    {"id": "ro-RO-EmilNeural", "engine": "edgetts", "lang": "ro-RO", "name": "Emil (Romanian male) — ONLINE"},
    {"id": "ja-JP-NanamiNeural", "engine": "edgetts", "lang": "ja-JP", "name": "Nanami (Japanese female) — ONLINE"},
]


def rate_to_percent(rate: float) -> str:
    """Map the aligner's speed factor onto edge-tts's signed percent string.

    1.0 -> "+0%", 1.15 -> "+15%", 0.9 -> "-10%". Clamped to ±50% so a wild
    ask can never produce an unintelligible take. Pure, unit-tested.
    """
    try:
        pct = int(round((float(rate) - 1.0) * 100.0))
    except (TypeError, ValueError):
        pct = 0
    pct = int(clamp(pct, RATE_PCT_MIN, RATE_PCT_MAX))
    return f"{pct:+d}%"


def build_mp3_to_wav_argv(in_mp3: str, out_wav: str, settings: dict[str, Any] | None = None) -> list[str]:
    """ffmpeg argv decoding the edge-tts MP3 into a PCM WAV (argv list, A6.4)."""
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_mp3,
        "-c:a",
        "pcm_s16le",
        out_wav,
    ]


def _default_factory(text: str, voice: str, rate_str: str) -> Any:
    """The real edge-tts Communicate (LAZY import — network lib, runtime only)."""
    import edge_tts  # noqa: PLC0415 - lazy: hosted engine, import on use  # pyright: ignore[reportMissingImports]  # optional runtime dep

    return edge_tts.Communicate(text, voice, rate=rate_str)


class EdgeTtsEngine(TtsEngine):
    """A4 hosted engine: Microsoft Edge neural voices (ONLINE)."""

    id = "edgetts"
    label = "Edge TTS (ONLINE)"
    online = True
    voice_clone = False

    def __init__(
        self,
        *,
        communicate_factory: CommunicateFactory | None = None,
        run: RunFn | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._factory: CommunicateFactory = communicate_factory or _default_factory
        self._run: RunFn = run or ffmpeg.run
        self._settings_provider = settings_provider or (lambda: {})

    def voices(self) -> list[Voice]:
        return [dict(v) for v in DEFAULT_VOICES]

    # -- A4 surface ------------------------------------------------------------
    def synth(
        self,
        cues: Sequence[Cue],
        voice: str,
        lang: str,
        out_wav: str,
        *,
        rate: float = 1.0,
    ) -> str:
        """Synthesize ``cues`` into one WAV via the hosted edge-tts service.

        The cue texts are joined into a single utterance (the dub pipeline
        calls per cue, so this is normally one cue). ``lang`` is advisory
        only — an edge-tts voice id already encodes its locale.
        """
        if not cues:
            raise TtsError("edgetts synth: no cues given")
        if not voice:
            raise TtsError("edgetts synth: a voice id is required")
        text = " ".join(str(c.get("text", "")).strip() for c in cues).strip()
        if not text:
            raise TtsError("edgetts synth: cues contained no speakable text")
        rate_str = rate_to_percent(rate)

        out = Path(out_wav)
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ms-edgetts-") as tmp:
            mp3_path = str(Path(tmp) / "take.mp3")
            try:
                communicate = self._factory(text, voice, rate_str)
                asyncio.run(communicate.save(mp3_path))
            except TtsError:
                raise
            except Exception as exc:  # noqa: BLE001 - network/service failure
                raise TtsError(f"edge-tts synthesis failed (ONLINE): {exc}") from exc
            if not Path(mp3_path).is_file():
                raise TtsError("edge-tts produced no audio")
            settings = self._settings()
            argv = build_mp3_to_wav_argv(mp3_path, str(out), settings)
            code = self._run(argv)
            if code != 0:
                raise TtsError(f"mp3->wav decode failed (ffmpeg exit {code})")
        return str(out)

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break a synth
            return {}


__all__ = [
    "DEFAULT_VOICES",
    "EdgeTtsEngine",
    "build_mp3_to_wav_argv",
    "rate_to_percent",
]
