"""Lip-sync (re-lip the on-screen mouth to a finished dub) — WU-B1.

Design: `docs/plans/v1.5/flagship-lip-sync-dub.md` §4 WU-B1 / §5.2. This module
is the PURE half; every heavy thing (torch, diffusers, cv2, the diffusion
weights) lives behind :class:`LipSyncBackend` and runs in an ISOLATED
subprocess env — the same shape as :mod:`.chatterbox` / :mod:`.chatterbox_runner`,
because torch is BANNED from the py3.12 sidecar env (A6 lesson 5).

Wire shape::

    tts.lipsync.start({videoId, audioTrackId, engine?, quality?,
                       likenessConsentAttested})
        -> {jobId} -> job.done {path, engine, syncConfidence}

LICENCE POSITION (re-verified 2026-08-08 — the plan doc's §3.2 verdict is
CORRECTED here, and the correction is the reason this lane is unblocked):

* **LatentSync** (`ByteDance/LatentSync`, `ByteDance/LatentSync-1.6`) — weights
  are tagged **`openrail++`** on the Hub; the GitHub repo's own `LICENSE` is
  **Apache-2.0** (code and weights differ, so both are recorded).
* **MuseTalk** (`TMElyralab/MuseTalk`) — weights tagged
  **`creativeml-openrail-m`**.
* **OpenRAIL IS NOT a non-commercial licence.** The CreativeML OpenRAIL-M and
  Open RAIL++-M grants are royalty-free and expressly permit hosting the model
  "for Third Party remote access purposes (e.g. software-as-a-service)". What
  they attach is a list of **behavioural use-restrictions** (Attachment A) plus
  an obligation to pass those restrictions down to downstream users. So the
  commercial blocker the plan doc records for this tier is a MISREADING of the
  licence class; the real obligations are (a) ship the notice, (b) flow the
  use-restrictions down, (c) do not perform a restricted use.
* **Wav2Lip is genuinely non-commercial** ("any form of commercial use is
  strictly prohibited") and is therefore in :data:`DENIED_ENGINES` — asking for
  it raises, so it cannot be reached by a typo or a future careless edit.
* UNVERIFIED (inline, and it is the reason the consent gate below is written the
  way it is): Attachment A of BOTH OpenRAIL variants has **eleven** items and
  **none of them names impersonation, likeness, identity, or a real person's
  image or voice**. A non-consensual deepfake is most plausibly caught by items
  3 (verifiably false information to harm others) and 5 (defame, disparage or
  harass) — but that is an INFERENCE about how the clause applies, not a
  verbatim prohibition. The settling experiment is a licence-counsel reading of
  Attachment A items 3/4/5 against a named non-consensual-relip fact pattern.
  The consent gate is therefore justified on EU AI Act Art. 50 transparency +
  the plan's own §5 ethics gate, NOT on a claimed OpenRAIL likeness clause.

CONSENT (two gates, both FAIL CLOSED — §5.2):

1. :func:`require_likeness_consent` — ``likenessConsentAttested`` must be the
   literal ``True``. Manipulating a real person's face is the higher-risk act,
   so the higher bar is on this method, not inherited from the dub.
2. :func:`require_sample_consent` — when the dub's audio track was voiced by a
   STORED CLONE sample, that sample must itself carry an attestation.
   CONTRACT-NOTE: the sibling lane (WU-A2) that adds ``consentAttested`` to
   ``VoiceSample`` is NOT on this branch, so today every stored sample lacks
   the field and this gate REFUSES — deliberately. An absent field reads as
   NOT attested; it never reads as "probably fine". When WU-A2 lands the rows
   carry the field and the gate passes without a change here.

BUILD FLAG: :func:`require_enabled` refuses unless ``lipSyncEnabled`` is the
literal ``True``. Default (and any unreadable settings store) is OFF.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ... import ffmpeg
from ...jobs import JobContext
from ...pathsafe import ensure_within
from ...protocol import ErrorCode, RpcContext, RpcError
from ...util import get_logger
from .engine import TtsError

log = get_logger("media_studio.tts.lipsync")


class LipSyncError(TtsError):
    """A lip-sync failure; surfaces via the job.done error payload (A6.3)."""


class LikenessConsentError(LipSyncError):
    """A consent gate refused (typed so the UI can route to the attestation)."""


# --------------------------------------------------------------------------- #
# engine registry — the VERIFIED licence facts, as data
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LipSyncEngineSpec:
    """One re-lip engine and its verified licence position.

    ``commercial`` and ``use_restricted`` are deliberately SEPARATE fields: an
    OpenRAIL model is commercial-OK *and* use-restricted, and collapsing the two
    into one "commercial?" boolean is exactly the misreading this module exists
    to correct.
    """

    id: str
    label: str
    repo: str
    weights_license: str
    code_license: str
    commercial: bool
    use_restricted: bool
    notice: str


#: Engines whose licence genuinely forbids commercial use. Named so a request
#: for one is a LOUD refusal rather than a silent "unknown engine" — the plan's
#: §3.2 row for Wav2Lip is correct and must stay unreachable.
DENIED_ENGINES: Mapping[str, str] = {
    "wav2lip": (
        "Wav2Lip is research/non-commercial only — its README states "
        "'any form of commercial use is strictly prohibited'. It is permanently "
        "excluded from Reframe; use latentsync or musetalk."
    ),
}

_OPENRAIL_NOTICE = (
    "Licensed under a Responsible-AI (OpenRAIL) licence: commercial use IS "
    "permitted, but the licence attaches behavioural use-restrictions "
    "(Attachment A) that you must not breach and must pass on to anyone you "
    "give the output or the model to. Re-lipping a real person without their "
    "consent is not a use Reframe supports."
)

ENGINES: Mapping[str, LipSyncEngineSpec] = {
    "latentsync": LipSyncEngineSpec(
        id="latentsync",
        label="LatentSync (ByteDance) — highest quality",
        repo="https://huggingface.co/ByteDance/LatentSync-1.6",
        weights_license="openrail++",
        code_license="Apache-2.0",
        commercial=True,
        use_restricted=True,
        notice=_OPENRAIL_NOTICE,
    ),
    "musetalk": LipSyncEngineSpec(
        id="musetalk",
        label="MuseTalk (Tencent) — real-time capable",
        repo="https://huggingface.co/TMElyralab/MuseTalk",
        weights_license="creativeml-openrail-m",
        code_license="MIT",
        commercial=True,
        use_restricted=True,
        notice=_OPENRAIL_NOTICE,
    ),
}

#: LatentSync is the quality leader, so it is the default (plan §4 WU-B1).
DEFAULT_ENGINE = "latentsync"

#: Plain ``str``, never ``Literal``/``Enum`` — the #282 schema introspector
#: raises ``UnsupportedTypeError`` on anything outside its supported set
#: (plan §10 A).
QUALITIES: tuple[str, ...] = ("fast", "quality")
DEFAULT_QUALITY = "quality"

#: settings key (WU-A4) — OFF unless explicitly, literally enabled.
SETTING_ENABLED = "lipSyncEnabled"
#: the wire param carrying the likeness attestation.
CONSENT_PARAM = "likenessConsentAttested"
#: the ``VoiceSample`` field WU-A2 adds; absent == not attested.
SAMPLE_CONSENT_FIELD = "consentAttested"


def engine_spec(engine_id: str) -> LipSyncEngineSpec:
    """The spec for ``engine_id``, or raise naming the allowed ids."""
    denial = DENIED_ENGINES.get(engine_id)
    if denial is not None:
        raise LipSyncError(denial)
    spec = ENGINES.get(engine_id)
    if spec is None:
        raise LipSyncError(f"unknown lip-sync engine: {engine_id} (expected one of {', '.join(sorted(ENGINES))})")
    return spec


def require_quality(quality: str) -> str:
    """Validate the ``quality`` selector (plain ``str``, closed set)."""
    if quality not in QUALITIES:
        raise LipSyncError(f"unknown quality: {quality} (expected one of {', '.join(QUALITIES)})")
    return quality


# --------------------------------------------------------------------------- #
# gates — every one FAILS CLOSED
# --------------------------------------------------------------------------- #
def lipsync_enabled(settings: Mapping[str, Any] | None) -> bool:
    """True only when ``lipSyncEnabled`` is the LITERAL ``True``.

    A truthy string/int is NOT an opt-in: this flag guards a face-manipulation
    path, so a sloppy value must read as OFF.
    """
    if not settings:
        return False
    return settings.get(SETTING_ENABLED) is True


def require_enabled(settings: Mapping[str, Any] | None) -> None:
    """Refuse unless the build/user has explicitly enabled lip-sync."""
    if not lipsync_enabled(settings):
        raise LipSyncError(
            "lip-sync is disabled: set the lipSyncEnabled setting to true to "
            "enable it (it ships OFF, and the OpenRAIL weights are a separate "
            "opt-in download with their own licence acceptance)"
        )


def require_likeness_consent(params: Mapping[str, Any]) -> None:
    """Refuse unless ``likenessConsentAttested`` is the LITERAL ``True``."""
    if params.get(CONSENT_PARAM) is not True:
        raise LikenessConsentError(
            f"{CONSENT_PARAM} must be true: lip-sync modifies a real person's "
            "on-screen likeness, so you must attest that you have the right to "
            "do so (you are the subject, or you hold their written permission)"
        )


def sample_consent_attested(sample: Mapping[str, Any] | None) -> bool:
    """True only when a stored voice sample carries a LITERAL ``True`` attestation.

    An absent field (every row on this branch — WU-A2 has not landed) is NOT
    attested. See the module docstring's CONSENT note.
    """
    if not sample:
        return False
    return sample.get(SAMPLE_CONSENT_FIELD) is True


def require_face_boxes(probe: Callable[[str], Any] | None, media_path: str) -> list[list[int]]:
    """Face rects from the MIT-licensed detector, or REFUSE.

    Fail-closed on purpose. Returning ``[]`` here would let the backend fall back
    to its own bundled detector — for a MuseTalk-class graph that is S3FD, which
    ships under NO LICENCE (plan §3.4), so a silent empty list would quietly
    reintroduce the exact weight #287 removed from this repo. A missing probe is
    therefore unfinished wiring to be surfaced, not a default to absorb.
    """
    if probe is None:
        raise LipSyncError(
            "no face-box provider is wired: lip-sync must be driven with boxes "
            "from the vendored MIT YuNet detector, because letting the engine "
            "detect faces itself pulls the unlicensed S3FD weight. Inject a "
            "face_boxes_probe (reuse reframe_multispeaker's YuNet output)"
        )
    boxes = [[int(v) for v in box] for box in probe(media_path)]
    if not boxes:
        raise LipSyncError(f"the face detector found no faces in {media_path} — there is no mouth to re-lip")
    return boxes


def require_sample_consent(sample_id: str, sample: Mapping[str, Any] | None) -> None:
    """Refuse when the dub's cloned voice has no stored consent attestation."""
    if sample is None:
        raise LikenessConsentError(
            f"the dub was voiced by cloned sample {sample_id!r}, which is no "
            "longer in the voice store — re-add it with a consent attestation "
            "before re-lipping"
        )
    if not sample_consent_attested(sample):
        raise LikenessConsentError(
            f"cloned voice sample {sample_id!r} carries no {SAMPLE_CONSENT_FIELD} "
            "record, so re-lipping it is refused: a voice clone and a face edit "
            "of the same person need attested consent for both"
        )


# --------------------------------------------------------------------------- #
# the isolated env — NOT YET A REGISTERED U4 ASSET (deliberately)
# --------------------------------------------------------------------------- #
#: The env dir the runner is executed against. The NAME is reserved here so the
#: install layout is decided in one place, but **no ``register_asset`` call
#: exists** and :func:`assets.ensure` cannot materialize it.
#:
#: That is deliberate, not an omission. The manifest validator requires exact
#: ``pkg==ver`` pins, and plan §10 D makes resolving LatentSync's real
#: torch/diffusers closure — and therefore whether it shares the chatterbox
#: py3.14 interpreter or needs a third embed — an explicit WU-B1 task that needs
#: a live pip resolve this lane could not run. Writing plausible-looking pins
#: would put a manifest LIE in the shipped asset set, the exact failure
#: ``chatterbox.py`` documents ("pinning torch 2.10 would be a manifest lie").
#: So the refusal below names the missing provisioning instead of pointing the
#: user at an ``assets.ensure`` call that would fail with "unknown asset".
#: ``test_tts_lipsync.py`` asserts the name is NOT in the manifest, so if someone
#: later registers it they are forced to update this message in the same commit.
LIPSYNC_ENV_ASSET = "latentsync-env"
LIPSYNC_ENV_DEST = "envs/latentsync"

# Subprocess runner seam: (argv, extra_env) -> (returncode, combined output).
RunCmd = Callable[[Sequence[str], dict[str, str] | None], tuple[int, str]]
RunFn = Callable[..., int]
#: (relipped_video, dub_audio) -> a sync-confidence score. NOT implemented here
#: (see the module docstring); the real SyncNet/LSE-C measurement is the opt-in
#: ``@e2e`` gate, which injects it.
ConfidenceProbe = Callable[[str, str], float]


def _default_run_cmd(argv: Sequence[str], extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run the runner subprocess with argv LISTS and fully-drained pipes.

    Mirrors :func:`..tts.chatterbox._default_run_cmd`: ``subprocess.run`` drains
    stdout/stderr via ``communicate()`` so a chatty diffusers load can never
    fill a pipe and freeze the sidecar (A6 lesson 2).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(  # noqa: S603 - argv list, shell never
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout or ""


def default_env_dir(root: str | None = None) -> str:
    """The lip-sync env's install dir under the assets root (A7 layout)."""
    from ...settings_store import default_config_dir  # noqa: PLC0415 - lazy

    base = Path(root) if root is not None else default_config_dir()
    return str(base / LIPSYNC_ENV_DEST)


def runner_dir() -> str:
    """The directory holding :mod:`.lipsync_runner` (this package)."""
    return str(Path(__file__).resolve().parent)


def build_relip_argv(python_exe: str, job_path: str) -> list[str]:
    """argv for one relip job: ``<env_python> -m lipsync_runner <job.json>``."""
    return [str(python_exe), "-m", "lipsync_runner", str(job_path)]


def runner_extra_env(env_dir: str) -> dict[str, str]:
    """``PYTHONPATH`` = the isolated env dir FIRST, then this package's dir."""
    return {"PYTHONPATH": os.pathsep.join([str(env_dir), runner_dir()])}


# --------------------------------------------------------------------------- #
# pure builders
# --------------------------------------------------------------------------- #
def build_relip_job_payload(
    *,
    video_path: str,
    audio_path: str,
    out_video: str,
    engine_id: str,
    quality: str = DEFAULT_QUALITY,
    boxes: Sequence[Sequence[int]] = (),
) -> dict[str, Any]:
    """The JSON job document the runner consumes (pure; the schema is ours).

    ``boxes`` are source-pixel ``(x, y, w, h)`` face rects, index-aligned to
    frames — reusing the already-shipped MIT YuNet detector's output
    (``reframe_multispeaker_backend._stage_visual``) so the bundled no-licence
    S3FD detector that MuseTalk-class code pulls by default is never needed
    (plan §3.4 / §10 C). Empty means "detect inside the backend".
    """
    return {
        "videoPath": str(video_path),
        "audioPath": str(audio_path),
        "outVideo": str(out_video),
        "engine": str(engine_id),
        "quality": str(quality),
        "boxes": [[int(v) for v in box] for box in boxes],
    }


def build_remux_argv(
    relipped_video: str,
    dub_audio: str,
    out_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """ffmpeg argv muxing the re-lipped VIDEO with the DUB audio (argv list, A6.4).

    Both streams are COPIED: the video was just generated by the diffusion
    backend (re-encoding it is a second generational loss for no benefit) and
    the dub audio is already the AAC the dub pipeline encoded.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(relipped_video),
        "-i",
        str(dub_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_path),
    ]


# --------------------------------------------------------------------------- #
# the backend seam
# --------------------------------------------------------------------------- #
class LipSyncBackend(Protocol):
    """What the pipeline needs from a re-lip engine (everything heavy)."""

    def relip(self, payload: dict[str, Any]) -> str:
        """Re-lip ``payload['videoPath']`` to ``payload['audioPath']``."""
        ...  # pragma: no cover - protocol

    def release(self) -> None:
        """Drop the model + free the GPU cache (one model at a time)."""
        ...  # pragma: no cover - protocol


class SubprocessLipSyncBackend:
    """Runs the relip in the ISOLATED env via ``-m lipsync_runner``.

    The subprocess call is behind the injectable :data:`RunCmd` seam, so every
    branch here is unit-tested without torch, a GPU, or a real spawn.
    """

    def __init__(
        self,
        *,
        env_dir: str | None = None,
        python_exe: str | None = None,
        run_cmd: RunCmd | None = None,
        assets_root: str | None = None,
    ) -> None:
        self.env_dir = env_dir or default_env_dir(assets_root)
        # The relip stack is torch/diffusers, so it runs on the SAME dedicated
        # py3.14 embeddable the chatterbox env uses (plan §10 D option (a)),
        # falling back to the host interpreter on a dev box without it — where
        # the env never registers as installed and relip refuses below anyway.
        from .chatterbox import default_chatterbox_python  # noqa: PLC0415 - lazy sibling

        self.python_exe = python_exe or default_chatterbox_python() or sys.executable
        self._run_cmd: RunCmd = run_cmd or _default_run_cmd

    def relip(self, payload: dict[str, Any]) -> str:
        """Spawn the runner and verify it produced the video."""
        if not Path(ensure_within(self.env_dir)).is_dir():
            raise LipSyncError(
                f"lip-sync env missing at {self.env_dir}: the {LIPSYNC_ENV_ASSET!r} "
                "environment is NOT YET PROVISIONED — it has no manifest entry, so "
                "assets.ensure cannot install it. Provisioning it requires pinned "
                "torch/diffusers versions plus a hashed lock, and an accepted "
                "OpenRAIL licence for the weights (plan WU-B1 / §10 D)"
            )
        out = Path(payload["outVideo"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ms-lipsync-") as tmp:
            job_path = Path(tmp) / "job.json"
            job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            argv = build_relip_argv(self.python_exe, str(job_path))
            code, output = self._run_cmd(argv, runner_extra_env(self.env_dir))
        if code != 0:
            tail = "\n".join((output or "").splitlines()[-12:])
            raise LipSyncError(f"lip-sync runner failed (exit {code}): {tail}")
        if not out.is_file():
            raise LipSyncError("lip-sync runner exited 0 but produced no video")
        return str(out)

    def release(self) -> None:
        """Nothing to free in this process — the model died with the subprocess."""
        return None


def default_backend_factory(engine_id: str, settings: Mapping[str, Any] | None) -> SubprocessLipSyncBackend:
    """Build the real (subprocess) backend for ``engine_id``."""
    engine_spec(engine_id)
    return SubprocessLipSyncBackend()


# --------------------------------------------------------------------------- #
# the pipeline
# --------------------------------------------------------------------------- #
_PCT_PREFLIGHT = (0.0, 5.0)
_PCT_RELIP = (5.0, 85.0)
_PCT_REMUX = (85.0, 100.0)


def _checkpoint(job_ctx: JobContext, band: tuple[float, float], frac: float, message: str) -> None:
    """Cooperative cancel point + banded progress (one helper, so every stage
    boundary is both cancellable and reported)."""
    job_ctx.raise_if_cancelled()
    lo, hi = band
    job_ctx.progress(lo + (hi - lo) * max(0.0, min(1.0, frac)), message)


def run_lipsync_pipeline(
    job_ctx: JobContext,
    *,
    video_path: str,
    audio_path: str,
    out_path: str,
    work_dir: str,
    backend: LipSyncBackend,
    engine_id: str = DEFAULT_ENGINE,
    quality: str = DEFAULT_QUALITY,
    boxes: Sequence[Sequence[int]] = (),
    run: RunFn = ffmpeg.run,
    settings: dict[str, Any] | None = None,
    confidence_probe: ConfidenceProbe | None = None,
) -> dict[str, Any]:
    """preflight -> relip (isolated env) -> remux with the dub audio.

    Returns ``{"path", "engine", "syncConfidence"}``. ``syncConfidence`` is
    ``None`` unless ``confidence_probe`` is injected — this module does NOT
    measure lip-sync quality, and reporting a fabricated number would be worse
    than reporting none (the real SyncNet/LSE-C gate is the ``@e2e`` tier).
    """
    spec = engine_spec(engine_id)
    require_quality(quality)
    _checkpoint(job_ctx, _PCT_PREFLIGHT, 0.0, f"preparing {spec.label}")
    if not Path(video_path).is_file():
        raise LipSyncError(f"source video not found: {video_path}")
    if not Path(audio_path).is_file():
        raise LipSyncError(f"dub audio not found: {audio_path}")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    raw_video = str(work / "relipped-raw.mp4")

    _checkpoint(job_ctx, _PCT_RELIP, 0.0, "re-lipping frames (this is the slow stage)")
    payload = build_relip_job_payload(
        video_path=video_path,
        audio_path=audio_path,
        out_video=raw_video,
        engine_id=engine_id,
        quality=quality,
        boxes=boxes,
    )
    try:
        produced = backend.relip(payload)
    except LipSyncError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface backend failures (A6.3)
        raise LipSyncError(f"re-lip failed: {exc}") from exc
    finally:
        # Free the GPU before the remux, and even on failure so a retry starts
        # clean (mirrors RealMultiSpeakerBackend's staged release).
        with contextlib.suppress(Exception):
            backend.release()
    if not Path(produced).is_file():
        raise LipSyncError("the backend reported success but wrote no re-lipped video")

    _checkpoint(job_ctx, _PCT_REMUX, 0.0, "muxing the dub audio onto the re-lipped video")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    code = run(build_remux_argv(produced, audio_path, str(out), settings))
    if code != 0:
        raise LipSyncError(f"lip-sync remux failed (ffmpeg exit {code})")
    if not out.is_file():
        raise LipSyncError("lip-sync remux reported success but produced no output file")

    confidence = float(confidence_probe(str(out), audio_path)) if confidence_probe is not None else None
    _checkpoint(job_ctx, _PCT_REMUX, 1.0, "lip-sync ready")
    return {"path": str(out), "engine": engine_id, "syncConfidence": confidence}


# --------------------------------------------------------------------------- #
# the service + tts.lipsync.start handler
# --------------------------------------------------------------------------- #
# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]
# (videoId, audioTrackId) -> the A3 AudioTrack row (or None when unknown).
AudioTrackLoader = Callable[[str, str], dict[str, Any] | None]
# sampleId -> the A3 VoiceSample row (or None when it is not a stored clone).
SampleGetter = Callable[[str], dict[str, Any] | None]
BackendFactory = Callable[[str, Mapping[str, Any] | None], LipSyncBackend]
#: (media_path) -> per-frame ``(x, y, w, h)`` face rects. The LICENCE-critical
#: seam: supplying boxes is what stops a MuseTalk-class backend reaching for its
#: bundled S3FD detector, which ships under NO LICENCE at all (plan §3.4). The
#: intended implementation reuses the already-vendored MIT YuNet output
#: (``reframe_multispeaker_backend._stage_visual`` -> ``_lightasd_infer.analyze_visual``),
#: which needs cv2, so it is INJECTED rather than imported here.
#:
#: UNVERIFIED, and it is the load-bearing residual of this lane: no caller wires
#: this yet, so a real run currently falls back to the backend's own detector and
#: the S3FD avoidance is a DESIGN INTENT, not an enforced property. The settling
#: experiment is an @e2e run with the probe wired, asserting the backend never
#: fetches an S3FD weight. Until then :meth:`LipSyncService.lipsync_start` refuses
#: rather than silently running undetected — see ``require_face_boxes``.
FaceBoxesProbe = Callable[[str], Sequence[Sequence[int]]]


class LipSyncService:
    """Owns the ``tts.lipsync.start`` wiring around :func:`run_lipsync_pipeline`."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        load_audio_track: AudioTrackLoader,
        get_sample: SampleGetter,
        backend_factory: BackendFactory | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn = ffmpeg.run,
        confidence_probe: ConfidenceProbe | None = None,
        face_boxes_probe: FaceBoxesProbe | None = None,
        out_dir: str | None = None,
    ) -> None:
        self._resolver = resolver
        self._load_audio_track = load_audio_track
        self._get_sample = get_sample
        self._backend_factory = backend_factory or default_backend_factory
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._confidence_probe = confidence_probe
        self._face_boxes_probe = face_boxes_probe
        self._out_dir = out_dir

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - an unreadable store must FAIL CLOSED
            log.warning("settings unreadable; lip-sync stays disabled")
            return {}

    def _out_dir_for(self, video_id: str) -> Path:
        if self._out_dir is not None:
            return Path(self._out_dir) / video_id
        from ...settings_store import default_config_dir  # noqa: PLC0415 - lazy

        return default_config_dir() / "lipsync" / video_id

    def lipsync_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tts.lipsync.start({...})`` -> ``{jobId}`` -> ``{path, engine, syncConfidence}``.

        Gate order is deliberate: the BUILD flag first (a disabled feature must
        not even look at the request), then the CONSENT attestation (before any
        media is touched), then ordinary validation.
        """
        settings = self._settings()
        _refuse_on(lambda: require_enabled(settings))
        _refuse_on(lambda: require_likeness_consent(params))

        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "audioTrackId")
        engine_id = params.get("engine", DEFAULT_ENGINE)
        if not isinstance(engine_id, str) or not engine_id:
            raise RpcError("engine must be a non-empty string", ErrorCode.INVALID_PARAMS)
        quality = params.get("quality", DEFAULT_QUALITY)
        if not isinstance(quality, str):
            raise RpcError("quality must be a string", ErrorCode.INVALID_PARAMS)
        _refuse_on(lambda: engine_spec(engine_id))
        _refuse_on(lambda: require_quality(quality))

        in_path = self._resolver(video_id)
        if not in_path:
            raise RpcError(f"unknown video: {video_id}", ErrorCode.INVALID_PARAMS)
        track = self._load_audio_track(video_id, track_id)
        if not track:
            raise RpcError(f"unknown audio track: {track_id}", ErrorCode.INVALID_PARAMS)
        if track.get("kind") != "dub":
            raise RpcError(
                f"audio track {track_id} is not a dub — lip-sync re-lips the mouth "
                "to a GENERATED dub track, not to the original audio",
                ErrorCode.INVALID_PARAMS,
            )
        audio_path = str(track.get("path") or "")
        if not audio_path or not Path(audio_path).is_file():
            raise RpcError(f"dub audio not found: {audio_path}", ErrorCode.INVALID_PARAMS)

        # The SECOND consent gate: a dub voiced by a stored CLONE means this
        # request manipulates both a person's voice and their face.
        voice = track.get("voice")
        if isinstance(voice, str) and voice:
            sample = self._get_sample(voice)
            if sample is not None:
                _refuse_on(lambda: require_sample_consent(voice, sample))

        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            out_base = self._out_dir_for(video_id)
            stamp = int(time.time())
            out_path = str(out_base / f"lipsync-{track_id}-{stamp}.mp4")
            work_dir = str(out_base / f"work-{track_id}-{stamp}")
            backend = self._backend_factory(engine_id, settings)
            boxes = require_face_boxes(self._face_boxes_probe, in_path)
            return run_lipsync_pipeline(
                job_ctx,
                video_path=in_path,
                audio_path=audio_path,
                out_path=out_path,
                work_dir=work_dir,
                backend=backend,
                engine_id=engine_id,
                quality=quality,
                boxes=boxes,
                run=self._run,
                settings=settings,
                confidence_probe=self._confidence_probe,
            )

        # gpu=True: the registry serializes gpu jobs to one worker, so a relip
        # never co-resides with another heavy model on a 6 GB GPU (plan §10 E).
        job = ctx.jobs.start(job_body, feature="lipsync", label="Lip-sync", videoId=video_id, gpu=True)
        return {"jobId": job.id}


def _refuse_on(call: Callable[[], Any]) -> None:
    """Run a gate and translate its typed refusal into an RPC error.

    The gates raise :class:`LipSyncError` so the pipeline can use them too; on
    the wire the same refusal must be an ``INVALID_PARAMS`` the UI can route.
    """
    try:
        call()
    except LipSyncError as exc:
        raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError(f"{key} (str) is required", ErrorCode.INVALID_PARAMS)
    return value


__all__ = [
    "CONSENT_PARAM",
    "FaceBoxesProbe",
    "DEFAULT_ENGINE",
    "DEFAULT_QUALITY",
    "DENIED_ENGINES",
    "ENGINES",
    "LIPSYNC_ENV_ASSET",
    "LIPSYNC_ENV_DEST",
    "QUALITIES",
    "SAMPLE_CONSENT_FIELD",
    "SETTING_ENABLED",
    "LikenessConsentError",
    "LipSyncBackend",
    "LipSyncEngineSpec",
    "LipSyncError",
    "LipSyncService",
    "SubprocessLipSyncBackend",
    "build_relip_argv",
    "build_relip_job_payload",
    "build_remux_argv",
    "default_backend_factory",
    "default_env_dir",
    "engine_spec",
    "lipsync_enabled",
    "require_enabled",
    "require_face_boxes",
    "require_likeness_consent",
    "require_quality",
    "require_sample_consent",
    "run_lipsync_pipeline",
    "runner_dir",
    "runner_extra_env",
    "sample_consent_attested",
]
