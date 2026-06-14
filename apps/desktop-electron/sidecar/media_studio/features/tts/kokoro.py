"""Kokoro TTS engine — the DEFAULT local engine (CONTRACTS.md A4, T2).

Uses the **kokoro-onnx** build (onnxruntime) — NEVER the torch ``kokoro`` pip
package (A4; no torch in the main sidecar env, A6 lesson 5). The model + voice
weights are U4 manifest assets (PINNED release URLs) registered below with
``register_asset`` — ``assets.ensure(["kokoro-v1.0-onnx","kokoro-voices-v1.0"])``
downloads them into ``%APPDATA%/media-studio/models/``.

A6 lesson 1 (NON-NEGOTIABLE): ``kokoro_onnx`` drags in **onnxruntime** (a
native C-extension). It is imported LAZILY inside ``synth`` here, so the
wiring agent MUST add ``"onnxruntime"`` and ``"kokoro_onnx"`` to
``__main__._preimport_native_modules`` — a first import on a job thread
deadlocks the sidecar (proven). See WIRING-T2.md.

The onnx session is injectable (``factory``) so unit tests never import
onnxruntime; WAV writing is stdlib ``wave`` (no soundfile — nothing else to
pre-import from this module).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ...assets.manifest import AssetEntry, register_asset
from ...settings_store import default_config_dir
from ...util import get_logger
from .engine import (
    Cue,
    TtsEngine,
    TtsError,
    Voice,
    float_samples_to_int16_bytes,
    write_pcm_wav,
)

log = get_logger("media_studio.tts.kokoro")

# --------------------------------------------------------------------------- #
# U4 manifest assets (PINNED — A6 lesson 5)
# --------------------------------------------------------------------------- #
KOKORO_MODEL_ASSET = "kokoro-v1.0-onnx"
KOKORO_VOICES_ASSET = "kokoro-voices-v1.0"

# Pinned to the kokoro-onnx project's immutable model-files-v1.0 release tag.
KOKORO_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
KOKORO_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)
KOKORO_MODEL_DEST = "models/kokoro-v1.0.onnx"
KOKORO_VOICES_DEST = "models/kokoro-voices-v1.0.bin"
KOKORO_MODEL_SIZE_MB = 326
KOKORO_VOICES_SIZE_MB = 27


def _register_assets() -> None:
    """Register the kokoro weights in the U4 manifest (idempotent re-register)."""
    register_asset(
        AssetEntry(
            name=KOKORO_MODEL_ASSET,
            kind="model",
            size_mb=KOKORO_MODEL_SIZE_MB,
            dest=KOKORO_MODEL_DEST,
            label="Kokoro v1.0 TTS model (onnx)",
            installer="download",
            url=KOKORO_MODEL_URL,
        )
    )
    register_asset(
        AssetEntry(
            name=KOKORO_VOICES_ASSET,
            kind="model",
            size_mb=KOKORO_VOICES_SIZE_MB,
            dest=KOKORO_VOICES_DEST,
            label="Kokoro v1.0 voice embeddings",
            installer="download",
            url=KOKORO_VOICES_URL,
        )
    )


_register_assets()


# --------------------------------------------------------------------------- #
# voice catalog (offline-safe built-in subset)
# --------------------------------------------------------------------------- #
# CONTRACT-NOTE: A2 freezes only the row shape {id, engine, lang, name}. The
# FULL voice list lives inside voices-v1.0.bin (readable only with the model
# loaded); this static subset keeps `tts.voices` instant and offline. Voice
# ids are kokoro-onnx's own (af_* = American female, am_* male, bf_/bm_ =
# British, ...).
DEFAULT_VOICES: List[Voice] = [
    {"id": "af_sarah", "engine": "kokoro", "lang": "en-us", "name": "Sarah (US female)"},
    {"id": "af_bella", "engine": "kokoro", "lang": "en-us", "name": "Bella (US female)"},
    {"id": "af_nicole", "engine": "kokoro", "lang": "en-us", "name": "Nicole (US female)"},
    {"id": "af_sky", "engine": "kokoro", "lang": "en-us", "name": "Sky (US female)"},
    {"id": "am_adam", "engine": "kokoro", "lang": "en-us", "name": "Adam (US male)"},
    {"id": "am_michael", "engine": "kokoro", "lang": "en-us", "name": "Michael (US male)"},
    {"id": "bf_emma", "engine": "kokoro", "lang": "en-gb", "name": "Emma (UK female)"},
    {"id": "bm_george", "engine": "kokoro", "lang": "en-gb", "name": "George (UK male)"},
]

#: lang fallback when the track/request gives none (kokoro-onnx lang codes).
DEFAULT_LANG = "en-us"

#: ISO 639 (track/transcript lang) -> kokoro-onnx/espeak language codes.
#: Tracks carry bare codes ("en", "eng"); kokoro's espeak backend wants
#: regioned ones ("en-us") — passing "en" raw fails (proven live in Phase-Z
#: smokes). Unknown codes pass through (kokoro accepts e.g. "fr-fr", "ja").
_LANG_MAP = {
    "en": "en-us",
    "eng": "en-us",
    "en-us": "en-us",
    "en-gb": "en-gb",
    "es": "es",
    "spa": "es",
    "fr": "fr-fr",
    "fra": "fr-fr",
    "ja": "ja",
    "jpn": "ja",
    "zh": "cmn",
    "cmn": "cmn",
    "hi": "hi",
    "hin": "hi",
    "it": "it",
    "ita": "it",
    "pt": "pt-br",
    "por": "pt-br",
}


def _kokoro_lang(lang: str, voice: str) -> str:
    """Map a track/request lang to a kokoro espeak code; voice prefix wins for
    English (a*=US, b*=UK voices)."""
    norm = (lang or "").strip().lower()
    mapped = _LANG_MAP.get(norm, norm or DEFAULT_LANG)
    if mapped.startswith("en-"):
        return "en-gb" if voice[:1] == "b" else "en-us"
    return mapped

# Factory seam: (model_path, voices_path) -> a Kokoro-like object exposing
# ``create(text, voice=..., speed=..., lang=...) -> (samples, sample_rate)``.
KokoroFactory = Callable[[str, str], Any]


def resolve_model_paths(
    root: Optional[str] = None,
) -> Dict[str, str]:
    """Absolute on-disk paths of the two kokoro assets (U4 layout).

    Mirrors the AssetManager's dest resolution: relative manifest dests live
    under the per-user config dir (``%APPDATA%/media-studio``).
    """
    base = Path(root) if root is not None else default_config_dir()
    return {
        "model": str(base / KOKORO_MODEL_DEST),
        "voices": str(base / KOKORO_VOICES_DEST),
    }


def _default_factory(model_path: str, voices_path: str) -> Any:
    """Build the real kokoro-onnx session (LAZY import — see module docstring)."""
    from kokoro_onnx import Kokoro  # noqa: PLC0415 - lazy: onnxruntime native

    return Kokoro(model_path, voices_path)


class KokoroEngine(TtsEngine):
    """A4 default local engine: kokoro-onnx via onnxruntime."""

    id = "kokoro"
    label = "Kokoro (local)"
    online = False
    voice_clone = False

    def __init__(
        self,
        *,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        assets_root: Optional[str] = None,
        factory: Optional[KokoroFactory] = None,
    ) -> None:
        paths = resolve_model_paths(assets_root)
        self.model_path = model_path or paths["model"]
        self.voices_path = voices_path or paths["voices"]
        self._factory: KokoroFactory = factory or _default_factory
        self._session: Any = None

    def voices(self) -> List[Voice]:
        return [dict(v) for v in DEFAULT_VOICES]

    # -- internals -----------------------------------------------------------
    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        for path, asset in (
            (self.model_path, KOKORO_MODEL_ASSET),
            (self.voices_path, KOKORO_VOICES_ASSET),
        ):
            if not Path(path).is_file():
                raise TtsError(
                    f"kokoro weights missing at {path} — install the "
                    f"{asset!r} asset first (assets.ensure)"
                )
        try:
            self._session = self._factory(self.model_path, self.voices_path)
        except Exception as exc:  # noqa: BLE001 - surface as a typed TTS failure
            raise TtsError(f"failed to load kokoro-onnx: {exc}") from exc
        return self._session

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
        """Synthesize ``cues`` into one WAV via kokoro-onnx.

        Each cue is generated separately (kokoro handles short utterances
        best) and the PCM is concatenated; ``rate`` maps onto kokoro's
        ``speed`` parameter (the aligner's re-synth ask).
        """
        if not cues:
            raise TtsError("kokoro synth: no cues given")
        if not voice:
            raise TtsError("kokoro synth: a voice id is required")
        session = self._ensure_session()
        lang = _kokoro_lang(lang, voice)
        frames = bytearray()
        sample_rate: Optional[int] = None
        for cue in cues:
            text = str(cue.get("text", "")).strip()
            if not text:
                continue
            try:
                samples, sr = session.create(
                    text, voice=voice, speed=float(rate), lang=lang
                )
            except Exception as exc:  # noqa: BLE001 - surface as a typed TTS failure
                raise TtsError(f"kokoro synthesis failed: {exc}") from exc
            if sample_rate is None:
                sample_rate = int(sr)
            elif int(sr) != sample_rate:  # pragma: no cover - model is consistent
                raise TtsError("kokoro returned inconsistent sample rates")
            frames += float_samples_to_int16_bytes(samples)
        if sample_rate is None or not frames:
            raise TtsError("kokoro synth: cues contained no speakable text")
        return write_pcm_wav(out_wav, bytes(frames), sample_rate=sample_rate)


__all__ = [
    "KOKORO_MODEL_ASSET",
    "KOKORO_VOICES_ASSET",
    "KOKORO_MODEL_URL",
    "KOKORO_VOICES_URL",
    "DEFAULT_VOICES",
    "DEFAULT_LANG",
    "KokoroEngine",
    "resolve_model_paths",
]
