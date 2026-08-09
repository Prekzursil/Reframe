"""Voice catalog + voice-sample store (CONTRACTS.md A2/A3, T2).

Owns two frozen A2 methods (registered via the package ``register()``):

  * ``tts.voices()`` -> ``{voices:[{id,engine,lang,name}]}`` — the union of
    every engine's built-in catalog plus the user's stored voice-clone
    samples (surfaced as ``engine:"chatterbox"`` rows so the UI's voice
    picker covers cloning too);
  * ``tts.sample.add({path})`` -> ``{sample: VoiceSample}`` — copies the
    given audio file into ``%APPDATA%/media-studio/voices/`` (A2: samples
    live there) and persists it in a small JSON index.

``VoiceSample`` (A3, field names FROZEN): ``{id, name, path, durationSec}``,
EXTENDED by WU-A2 with the consent record ``{consentAttested, consentAt,
consentNote}``.

WU-A2 — the voice-clone CONSENT gate (the LEGAL keystone;
``docs/plans/v1.5/flagship-lip-sync-dub.md`` §4 WU-A2 + §5.1). Cloning a
person's voice without an attested right to do so is the flagship's headline
legal exposure (EU AI Act Art. 50 transparency duties), so:

  * ``tts.sample.add`` REQUIRES ``consentAttested is True`` and refuses
    otherwise with a typed ``INVALID_PARAMS``;
  * :meth:`VoiceStore.add` re-checks the attestation BEFORE it touches the
    filesystem, so no code path can persist a clone reference without one;
  * :func:`require_consent` is the clone-time gate (``tts.dub.start`` calls it
    through ``dub.DubService._resolve_voice``) so a LEGACY row backfilled as
    ``consentAttested: False`` cannot be cloned either;
  * the attestation timestamp ``consentAt`` is UTC ISO-8601 and the clock is
    injectable, so the record is deterministic under test.

CONTRACT-NOTE: this is a SEPARATE gate from :mod:`media_studio.models.consent`,
which is a per-provider text/frames EGRESS gate. That module is the *idiom*
mirrored here (typed refusal + default-deny), not the mechanism — see
``docs/plans/v1.5/flagship-lip-sync-dub.md:57``. This gate has NO settings opt-out in this
lane; ``requireVoiceConsent`` belongs to WU-A4 (settings surface).

Pure logic + filesystem I/O; the duration probe is injectable (defaults to
the lazy ffprobe seam) so tests never spawn a process.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...pathsafe import ensure_within
from ...protocol import ErrorCode, RpcContext, RpcError
from ...settings_store import default_config_dir
from ...util import get_logger
from .engine import TtsEngine, TtsError, Voice

log = get_logger("media_studio.tts.voices")

#: A3 VoiceSample (frozen field names) + the WU-A2 consent record.
VoiceSample = dict[str, Any]

# Injectable duration probe: (path) -> seconds.
DurationProber = Callable[[str], float]
# Injectable UTC ISO-8601 clock for the consent record.
ConsentClock = Callable[[], str]

_INDEX_FILENAME = "voices.json"
_INDEX_VERSION = 1

#: sample formats we accept for cloning references.
_SAMPLE_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus")

#: The exact attestation the user makes. The renderer's blocking checkbox
#: (``app/renderer/src/features/Dub.tsx``) shows this same sentence — keep the
#: two in step; the refusal message quotes it so the UI can never claim a
#: weaker promise than the one the backend enforces.
CONSENT_ATTESTATION_TEXT = "I own this voice or have the speaker's documented permission to clone it."


def default_voices_dir() -> Path:
    """``%APPDATA%/media-studio/voices`` (A2: where samples live)."""
    return default_config_dir() / "voices"


def _default_probe(path: str) -> float:
    """ffprobe duration via the lazy ffmpeg seam (import-light module)."""
    from ... import ffmpeg  # noqa: PLC0415 - lazy: keep voices import-light

    return ffmpeg.ffprobe_duration(path)


def _utc_now_iso() -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` — UTC, so a consent record has no local-time ambiguity."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# WU-A2 consent primitives (pure; mirrors models.consent's default-deny idiom)
# --------------------------------------------------------------------------- #
class VoiceConsentError(TtsError):
    """Typed refusal: a voice-clone act with no consent attestation on record.

    A :class:`~.engine.TtsError` so the existing RPC boundaries (which already
    convert ``TtsError`` to a typed ``INVALID_PARAMS``) surface it correctly
    instead of leaking a 500.
    """

    def __init__(self, sample_id: str | None = None) -> None:
        self.sample_id = sample_id
        subject = f"voice sample {sample_id!r}" if sample_id else "this voice sample"
        super().__init__(
            f"voice clone refused: no consent attestation on record for {subject} — {CONSENT_ATTESTATION_TEXT}"
        )


def consent_attested(sample: object) -> bool:
    """Default-deny predicate: ONLY an explicit stored ``True`` is an attestation.

    A missing row, a malformed row, ``False``, ``None`` and truthy-but-not-``True``
    values (``"true"``, ``1``) all read as NOT attested — consent must be an
    explicit, present ``True``, never an absence or a coincidence of truthiness.
    """
    if not isinstance(sample, Mapping):
        return False
    return sample.get("consentAttested") is True


def require_consent(sample: object, sample_id: str | None = None) -> None:
    """Raise :class:`VoiceConsentError` unless ``sample`` carries an attestation.

    The single clone-time enforcement point: called BEFORE a stored sample's
    audio path is handed to a voice-clone engine, so a legacy row (backfilled
    ``consentAttested: False``) is refused just like a consent-less add.
    """
    if not consent_attested(sample):
        raise VoiceConsentError(sample_id)


def _clean_note(note: object) -> str | None:
    """A consent note is free text; blank / non-string normalizes to ``None``."""
    if not isinstance(note, str):
        return None
    return note.strip() or None


def normalize_sample(raw: dict[str, Any]) -> VoiceSample:
    """Backfill a stored row to the full A3 VoiceSample + WU-A2 consent shape.

    A pre-WU-A2 row has no consent fields; it backfills to ``consentAttested:
    False`` (default-deny) so an existing library keeps listing but can no
    longer be cloned until the user re-attests.
    """
    attested = consent_attested(raw)
    consent_at = raw.get("consentAt")
    return {
        "id": str(raw.get("id") or _new_id()),
        "name": str(raw.get("name") or "sample"),
        "path": str(raw.get("path") or ""),
        "durationSec": float(raw.get("durationSec") or 0.0),
        "consentAttested": attested,
        "consentAt": consent_at if attested and isinstance(consent_at, str) and consent_at else None,
        "consentNote": _clean_note(raw.get("consentNote")),
    }


class VoiceStore:
    """The on-disk voice-sample collection (JSON index + copied audio files)."""

    def __init__(
        self,
        samples_dir: str | os.PathLike | None = None,
        *,
        duration_probe: DurationProber | None = None,
        now: ConsentClock | None = None,
    ) -> None:
        raw_dir = Path(samples_dir) if samples_dir is not None else default_voices_dir()
        # Canonicalise the voices base through the ensure_within barrier so the
        # mkdir sinks below operate on a realpath-normalised dir (CodeQL
        # py/path-injection); files under it are then confined via ensure_within too.
        self.samples_dir = Path(ensure_within(raw_dir))
        self.index_path = Path(ensure_within(self.samples_dir, _INDEX_FILENAME))
        self._probe = duration_probe or _default_probe
        self._now = now or _utc_now_iso

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

    def add(
        self,
        path: str,
        name: str | None = None,
        *,
        consent_attested: bool = False,
        consent_note: object = None,
    ) -> VoiceSample:
        """Copy ``path`` into the voices dir and persist a VoiceSample row.

        WU-A2: ``consent_attested`` must be exactly ``True`` — the check runs
        FIRST, before the file is even stat'd, so a consent-less add leaves the
        store byte-identical (no copied audio, no index row). The attestation
        default is ``False`` so a caller must opt IN, never out.

        The source file is COPIED (the store owns its bytes — a user moving
        the original later cannot break cloning). Duration is probed through
        the injectable seam; a probe failure stores 0.0 rather than blocking.
        """
        if consent_attested is not True:
            raise VoiceConsentError()
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
            "consentAttested": True,
            "consentAt": self._now(),
            "consentNote": _clean_note(consent_note),
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

    WU-A2: a row with NO attestation (a legacy sample) still LISTS — hiding a
    user's own data would be worse — but its label says so, because picking it
    will be refused by :func:`require_consent` at dub time. The A2 ``Voice``
    shape stays frozen at four keys, so the label is the only channel.
    """
    return [
        {
            "id": s["id"],
            "engine": "chatterbox",
            "lang": "und",
            "name": f"{s['name']} (cloned sample)"
            if consent_attested(s)
            else f"{s['name']} (cloned sample — consent required)",
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
    """Build ``tts.sample.add({path, name?, consentAttested, consentNote?})`` (A2 + WU-A2).

    ``consentAttested`` is REQUIRED and must be exactly ``True``; anything else
    (absent, ``False``, ``"true"``, ``1``) is a typed ``INVALID_PARAMS``
    refusal and NOTHING is stored. ``consentNote`` is optional free text.
    """

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        path = params.get("path")
        if not isinstance(path, str) or not path:
            raise RpcError("path (str) is required", ErrorCode.INVALID_PARAMS)
        if params.get("consentAttested") is not True:
            raise RpcError(
                f"consentAttested (true) is required to store a voice clone — {CONSENT_ATTESTATION_TEXT}",
                ErrorCode.INVALID_PARAMS,
            )
        name = params.get("name")
        try:
            sample = store.add(
                path,
                name if isinstance(name, str) else None,
                consent_attested=True,
                consent_note=params.get("consentNote"),
            )
        except TtsError as exc:
            raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc
        return {"sample": sample}

    return handler


__all__ = [
    "CONSENT_ATTESTATION_TEXT",
    "VoiceConsentError",
    "VoiceSample",
    "VoiceStore",
    "consent_attested",
    "default_voices_dir",
    "make_sample_add_handler",
    "make_voices_handler",
    "normalize_sample",
    "require_consent",
    "samples_as_voices",
]
