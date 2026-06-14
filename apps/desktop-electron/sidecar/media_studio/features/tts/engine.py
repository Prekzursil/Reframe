"""TtsEngine interface + tiny shared audio helpers (CONTRACTS.md A4, T2).

A4 freezes the engine interface as ``TtsEngine.synth(cues, voice, lang,
out_wav)`` with exactly three implementations in this build:

  * **kokoro**     — default local (``kokoro-onnx`` build, onnxruntime;
                     NEVER the torch pip package) — :mod:`.kokoro`
  * **edgetts**    — hosted, labeled ONLINE — :mod:`.edgetts`
  * **chatterbox** — voice-clone, runs in its OWN downloaded env as a
                     subprocess (torch stays OUT of the main sidecar env)
                     — :mod:`.chatterbox`

CONTRACT-NOTE: the dub alignment recipe (A4, FROZEN) includes a "rate
re-synth" step — the aligner asks the engine to re-synthesize a cue at a
different speaking rate. A4 freezes the four positional parameters of
``synth``; we extend it with a keyword-only ``rate`` (default ``1.0`` = the
plain A4 call) rather than inventing a second public method. Engines that
cannot honor a rate simply ignore it.

This module is dependency-free (stdlib only): no onnxruntime / edge-tts /
torch import happens here or at package import time — each engine lazily
imports its backend inside ``synth`` (A6 lesson 1 notes the native modules
the wiring agent must pre-import in ``__main__``).
"""
from __future__ import annotations

import abc
import struct
import wave
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Sequence

from ...util import get_logger

log = get_logger("media_studio.tts.engine")

# Type aliases mirroring CONTRACTS.md §3 / A2 (field names frozen).
Cue = Dict[str, Any]
#: ``tts.voices()`` row shape (A2): {id, engine, lang, name}
Voice = Dict[str, Any]

#: Default PCM format every engine's out_wav is normalized to by the aligner
#: (mono 24 kHz s16le — kokoro's native rate; edge-tts/chatterbox outputs are
#: resampled to it by the per-cue ffmpeg align pass so concat is trivial).
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # bytes (s16le)


class TtsError(Exception):
    """A TTS synthesis failure; surfaces via the job.done error payload (A6.3)."""


class TtsEngine(abc.ABC):
    """The A4 TTS engine interface — exactly three impls in this build.

    Class metadata drives the UI/registry:

    * ``id``     — the wire engine id (``tts.dub.start({engine})`` value).
    * ``label``  — human name for pickers.
    * ``online`` — True when synthesis NEEDS the network at runtime (edgetts);
      the UI labels such engines ONLINE.
    * ``voice_clone`` — True when ``voice`` is a reference-sample path
      (chatterbox) rather than a named voice id.
    """

    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    online: ClassVar[bool] = False
    voice_clone: ClassVar[bool] = False

    @abc.abstractmethod
    def synth(
        self,
        cues: Sequence[Cue],
        voice: str,
        lang: str,
        out_wav: str,
        *,
        rate: float = 1.0,
    ) -> str:
        """Synthesize ``cues``' text into a single WAV at ``out_wav``.

        Returns ``out_wav``. ``voice`` is an engine voice id (or, for a
        voice-clone engine, the reference sample's path). ``rate`` is the
        keyword-only re-synth speed factor (1.0 = natural; 1.2 = 20% faster)
        used by the A4 alignment recipe. Raises :class:`TtsError` on failure.
        """

    def voices(self) -> List[Voice]:
        """Static voice catalog rows ``{id, engine, lang, name}`` (A2).

        Offline-safe: never hits the network or loads a model. Engines with a
        dynamic catalog return a representative built-in subset here.
        """
        return []


# --------------------------------------------------------------------------- #
# tiny shared WAV helpers (stdlib only — no soundfile/numpy dependency)
# --------------------------------------------------------------------------- #
def cues_text(cues: Sequence[Cue]) -> str:
    """Join the cues' text into one utterance (engine-level synth of a batch)."""
    return " ".join(str(c.get("text", "")).strip() for c in cues).strip()


def float_samples_to_int16_bytes(samples: Sequence[float]) -> bytes:
    """Convert float samples (-1..1) to packed little-endian s16 bytes.

    Works on plain Python sequences AND numpy arrays (via the fast path) so
    engine tests never need numpy. Out-of-range samples are clamped.
    """
    # Fast path: a numpy-like array with astype/tobytes.
    astype = getattr(samples, "astype", None)
    if astype is not None:
        try:
            import numpy as _np  # noqa: PLC0415 - only on the numpy fast path

            clipped = _np.clip(_np.asarray(samples, dtype=_np.float64), -1.0, 1.0)
            return (clipped * 32767.0).astype("<i2").tobytes()
        except Exception:  # noqa: BLE001 - fall through to the pure path
            pass
    out = bytearray()
    for s in samples:
        v = max(-1.0, min(1.0, float(s)))
        out += struct.pack("<h", int(v * 32767.0))
    return bytes(out)


def write_pcm_wav(
    out_path: str,
    frames: bytes,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> str:
    """Write raw PCM ``frames`` to ``out_path`` as a WAV file; return the path."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    return str(p)


def wav_duration_sec(path: str) -> float:
    """Duration of a WAV file in seconds via the stdlib ``wave`` reader.

    Returns 0.0 for an unreadable/empty file rather than raising — the
    aligner treats 0 as "nothing to align" and the caller surfaces a better
    error from the synthesis step itself.
    """
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return wf.getnframes() / float(rate)
    except (OSError, wave.Error, EOFError):
        return 0.0


__all__ = [
    "Cue",
    "Voice",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_CHANNELS",
    "DEFAULT_SAMPLE_WIDTH",
    "TtsError",
    "TtsEngine",
    "cues_text",
    "float_samples_to_int16_bytes",
    "write_pcm_wav",
    "wav_duration_sec",
]
