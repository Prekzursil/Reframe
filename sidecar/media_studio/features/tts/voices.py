"""Voice catalog + voice-sample store (CONTRACTS.md A2/A3, T2).

Owns two frozen A2 methods (registered via the package ``register()``):

  * ``tts.voices()`` -> ``{voices:[{id,engine,lang,name}]}`` — the union of
    every engine's built-in catalog plus the user's stored voice-clone
    samples (surfaced as ``engine:"chatterbox"`` rows so the UI's voice
    picker covers cloning too);
  * ``tts.sample.add({path})`` -> ``{sample: VoiceSample}`` — copies the
    given audio file into ``%APPDATA%/media-studio/voices/`` (A2: samples
    live there) and persists it in a small JSON index.

``VoiceSample`` (A3, field names FROZEN): ``{id, name, path, durationSec}``.

Pure logic + filesystem I/O; the duration probe is injectable (defaults to
the lazy ffprobe seam) so tests never spawn a process.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ...protocol import ErrorCode, RpcContext, RpcError
from ...settings_store import default_config_dir
from ...util import get_logger
from .engine import TtsEngine, TtsError, Voice

log = get_logger("media_studio.tts.voices")

#: A3 VoiceSample (frozen field names)
VoiceSample = dict[str, Any]

# Injectable duration probe: (path) -> seconds.
DurationProber = Callable[[str], float]

_INDEX_FILENAME = "voices.json"
_INDEX_VERSION = 1

#: sample formats we accept for cloning references.
_SAMPLE_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus")


def default_voices_dir() -> Path:
    """``%APPDATA%/media-studio/voices`` (A2: where samples live)."""
    return default_config_dir() / "voices"


def _default_probe(path: str) -> float:
    """ffprobe duration via the lazy ffmpeg seam (import-light module)."""
    from ... import ffmpeg  # noqa: PLC0415 - lazy: keep voices import-light

    return ffmpeg.ffprobe_duration(path)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_sample(raw: dict[str, Any]) -> VoiceSample:
    """Backfill a stored row to the full A3 VoiceSample shape."""
    return {
        "id": str(raw.get("id") or _new_id()),
        "name": str(raw.get("name") or "sample"),
        "path": str(raw.get("path") or ""),
        "durationSec": float(raw.get("durationSec") or 0.0),
    }


class VoiceStore:
    """The on-disk voice-sample collection (JSON index + copied audio files)."""

    def __init__(
        self,
        samples_dir: str | os.PathLike | None = None,
        *,
        duration_probe: DurationProber | None = None,
    ) -> None:
        self.samples_dir = Path(samples_dir) if samples_dir is not None else default_voices_dir()
        self.index_path = self.samples_dir / _INDEX_FILENAME
        self._probe = duration_probe or _default_probe

    # -- index I/O -----------------------------------------------------------
    def _load(self) -> builtins.list[VoiceSample]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            log.warning("voice sample index unreadable; starting empty")
            return []
        rows = data.get("samples", []) if isinstance(data, dict) else []
        return [normalize_sample(r) for r in rows if isinstance(r, dict)]

    def _save(self, samples: builtins.list[VoiceSample]) -> None:
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_name(self.index_path.name + ".tmp")
        tmp.write_text(
            json.dumps(
                {"version": _INDEX_VERSION, "samples": samples},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.index_path)

    # -- public surface --------------------------------------------------------
    def list(self) -> builtins.list[VoiceSample]:
        """All stored samples (A3 VoiceSample rows)."""
        return self._load()

    def get(self, sample_id: str) -> VoiceSample | None:
        for sample in self._load():
            if sample["id"] == sample_id:
                return sample
        return None

    def add(self, path: str, name: str | None = None) -> VoiceSample:
        """Copy ``path`` into the voices dir and persist a VoiceSample row.

        The source file is COPIED (the store owns its bytes — a user moving
        the original later cannot break cloning). Duration is probed through
        the injectable seam; a probe failure stores 0.0 rather than blocking.
        """
        src = Path(path)
        if not src.is_file():
            raise TtsError(f"voice sample not found: {path}")
        if src.suffix.lower() not in _SAMPLE_SUFFIXES:
            raise TtsError(f"unsupported sample format {src.suffix!r} (expected one of {', '.join(_SAMPLE_SUFFIXES)})")
        sample_id = _new_id()
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        dest = self.samples_dir / f"{sample_id}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        try:
            duration = float(self._probe(str(dest)))
        except Exception:  # noqa: BLE001 - a probe failure must not block adding
            duration = 0.0
        sample: VoiceSample = {
            "id": sample_id,
            "name": name or src.stem,
            "path": str(dest),
            "durationSec": duration,
        }
        samples = self._load()
        samples.append(sample)
        self._save(samples)
        return sample


def samples_as_voices(samples: Sequence[VoiceSample]) -> list[Voice]:
    """Stored clone samples as A2 voice rows (engine = chatterbox).

    CONTRACT-NOTE: a voice-clone engine has no named catalog; surfacing each
    sample as ``{id: <sampleId>, engine: "chatterbox", lang: "und", name}``
    gives the picker one uniform list. The id doubles as the ``sampleId``
    param of ``tts.dub.start``.
    """
    return [
        {
            "id": s["id"],
            "engine": "chatterbox",
            "lang": "und",
            "name": f"{s['name']} (cloned sample)",
        }
        for s in samples
    ]


# --------------------------------------------------------------------------- #
# handlers (the package register() wires these onto protocol.METHODS)
# --------------------------------------------------------------------------- #
def make_voices_handler(
    engines: Sequence[TtsEngine], store: VoiceStore
) -> Callable[[dict[str, Any], RpcContext], dict[str, Any]]:
    """Build ``tts.voices()`` -> ``{voices}`` (A2). Direct-return, offline."""

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        voices: list[Voice] = []
        for engine in engines:
            try:
                voices.extend(engine.voices())
            except Exception:  # noqa: BLE001 - one engine must not hide the rest
                log.warning("voice catalog failed for engine %s", engine.id)
        voices.extend(samples_as_voices(store.list()))
        return {"voices": voices}

    return handler


def make_sample_add_handler(
    store: VoiceStore,
) -> Callable[[dict[str, Any], RpcContext], dict[str, Any]]:
    """Build ``tts.sample.add({path})`` -> ``{sample: VoiceSample}`` (A2)."""

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        path = params.get("path")
        if not isinstance(path, str) or not path:
            raise RpcError("path (str) is required", ErrorCode.INVALID_PARAMS)
        name = params.get("name")
        try:
            sample = store.add(path, name if isinstance(name, str) else None)
        except TtsError as exc:
            raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc
        return {"sample": sample}

    return handler


__all__ = [
    "VoiceSample",
    "VoiceStore",
    "default_voices_dir",
    "make_sample_add_handler",
    "make_voices_handler",
    "normalize_sample",
    "samples_as_voices",
]
