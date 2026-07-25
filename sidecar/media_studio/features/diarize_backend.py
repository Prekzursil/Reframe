"""Real SpeechBrain VAD + ECAPA backend for diarization (LAZY-imported only).

The :class:`SpeechBrainDiarizer` itself is built ONLY inside
``diarize._default_backend_factory`` at job run-time (the tests inject a fake
:class:`~media_studio.features.diarize.DiarizerBackend` instead). This is the one
place allowed to import ``speechbrain`` / ``torch`` / ``torchaudio``, and those
imports live inside the methods so importing THIS module stays light — which is
what lets ``pyannote_backend`` / ``parakeet_asr_backend`` (and the tests) import
the shared :func:`resolve_pinned_hf_source` from here at module scope without
pulling in any native stack.

The :class:`SpeechBrainDiarizer`:
  1. runs SpeechBrain's pretrained ``VAD`` (CRDNN) to get speech boundaries;
  2. loads the audio with torchaudio, slices each speech region, and embeds it
     with the pretrained ``EncoderClassifier`` (ECAPA-TDNN);
  3. returns ``(regions, embeddings)`` for the pure clustering in ``diarize``.

Models resolve from the standard HF cache that ``assets.ensure`` populates, so a
machine that pre-fetched the gated assets runs this fully offline. Coverage of
this module is excluded (it requires the heavy native stack + real audio); the
pure pipeline it feeds is covered exhaustively in ``test_diarize.py``.

WU-S5 (revision pinning): the load calls resolve their HF revision from the ASSET
REGISTRY (:func:`resolve_pinned_hf_source`) instead of fetching a floating Hub
ref. ``assets/manifest.py`` already refuses to register an ``installer="hf"``
entry without a 40-hex commit pin, so making the registry the single source of
truth means a runtime load CANNOT drift from its registration. That matters here
because a SpeechBrain ``from_hparams`` executes code at load time — HyperPyYAML
``!new`` / ``!apply`` constructors in ``hyperparams.yaml`` plus an optional
``custom.py``, both of which the pin covers (see :func:`pinned_fetch_kwargs` for
the per-version kwarg shape and exactly how far each version's pin reaches).
:func:`resolve_pinned_hf_source` is the SHARED resolver for all three heavy HF
backends (this module, ``parakeet_asr_backend``, ``pyannote_backend``); it lives
here because this module is the lightest of the three at import time (its heavy
imports are all inside methods, and it registers no assets as a side effect).
"""

from __future__ import annotations

import re
from typing import Any

from ..assets import manifest
from ..util import get_logger
from .diarize import ECAPA_ASSET_NAME, ECAPA_HF_REPO, VAD_ASSET_NAME, VAD_HF_REPO, CancelProbe, ProgressCb

log = get_logger("media_studio.features.diarize_backend")

#: A registered HF revision must be a 40-hex git/HF COMMIT hash — a branch/tag
#: like "main" is a MOVING target. This DELIBERATELY duplicates the registration
#: gate (``manifest._COMMIT_HASH_RE``) as a defense-in-depth re-check at the LOAD
#: site, so a loosened registry cannot silently unpin a model load; the two
#: patterns are asserted identical in ``test_runtime_revision_pin.py``.
_COMMIT_HASH_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")

#: ECAPA expects 16 kHz mono; VAD is trained at 16 kHz too.
TARGET_SR = 16000

#: Sub-segmentation of each VAD speech region (seconds). VAD finds SPEECH vs
#: silence, NOT speaker turns, so a continuous interview collapses into one giant
#: region. Embedding one vector per region would then yield a single speaker. We
#: instead slide a fixed window across each region and embed each window, giving
#: time-resolved embeddings so the greedy cosine clustering can discriminate the
#: speakers within one continuous-speech region (standard diarization practice).
#: 2.5 s / 1.25 s was chosen empirically on the razvan interview: shorter windows
#: (1.5 s) yield noisier ECAPA vectors that over-fragment a single speaker, while
#: 2.5 s gives stable clusters (a 90 s sample resolves to the 2 true speakers).
WINDOW_SEC = 2.5
HOP_SEC = 1.25
#: Drop a trailing sub-window shorter than this (too little speech to embed well).
MIN_WINDOW_SEC = 0.5

#: Cosine-similarity clustering threshold for the SUB-WINDOW regime. ECAPA vectors
#: from ~2.5 s windows sit a little lower than from full utterances, so this floor
#: (below the long-utterance default 0.50 in ``diarize.DEFAULT_THRESHOLD``) keeps
#: same-speaker windows together while still separating real turns.
#:
#: Tuned to 0.45 (was 0.40): an embedding sweep over three fresh-scanned razvan
#: windows on the RTX 4050 (Phase-4 revalidation, 2026-06-29) showed 0.40
#: OVER-clustered the 30 s two-person window down to a SINGLE speaker, while 0.45
#: is the floor of the stable 0.45-0.60 plateau that resolves it to the true 2
#: speakers (the minority cluster two contiguous windows at 25.0-28.8 s — a real
#: interjection turn, not scattered noise). 0.45 simultaneously keeps the
#: one-speaker window at exactly 1 cluster (>= 0.50 over-fragments it into a
#: spurious singleton) and the three-person window at 2 clusters — the only value
#: correct for all three. Raising further fragments single speakers.
SUBWINDOW_CLUSTER_THRESHOLD = 0.45


class DiarizeBackendUnavailableError(RuntimeError):
    """SpeechBrain (the diarizer's VAD + ECAPA backend) is not importable.

    A SETUP/PROVISIONING failure, NOT a per-clip event: without ``speechbrain``
    the diarizer cannot run VAD or embed speakers at all, so the multi-speaker
    reframe's diarize stage (and ``diarize.start``) cannot run. It is raised as an
    EXPLICIT, typed, actionable signal — never a raw :class:`ModuleNotFoundError`
    bubbling out of a job thread, and never a silent fallback — so the job
    surfaces an install/provision message (v1.2.0 NO-SILENT-FALLBACK, mirroring
    ``reframe_claudeshorts.ClaudeShortsBackendUnavailableError``).
    """


class UnpinnedModelRevisionError(RuntimeError):
    """A heavy model load could not be pinned to its registered asset revision.

    A CONFIGURATION/PROVISIONING failure, not a per-clip event: the asset the
    loader is about to fetch is missing from the registry, is not an ``hf`` entry,
    names a different repo than the load site, or carries a revision that is not
    an immutable 40-hex commit. Every one of those means the load would resolve a
    MUTABLE upstream ref, and these formats execute code at load time — so the
    only safe outcome is to FAIL CLOSED with an actionable message (mirroring
    :class:`DiarizeBackendUnavailableError`'s typed no-silent-fallback contract)
    rather than fetch whatever the Hub currently serves.
    """


def resolve_pinned_hf_source(asset_name: str, expected_repo: str) -> tuple[str, str]:
    """Return ``(repo_id, revision)`` for ``asset_name`` from the ASSET REGISTRY.

    The registry — not a constant in the loading module — is the single source of
    truth for the revision a runtime load may use, so the load can never drift
    from the pin ``assets.ensure`` downloaded. ``expected_repo`` is the repo the
    caller is about to load; a mismatch means the registration and the load site
    were edited independently and is refused (that check IS the anti-drift
    mechanism). Raises :class:`UnpinnedModelRevisionError` when the entry is
    absent, is not an ``installer="hf"`` entry (only those carry the manifest's
    validated commit pin), names a different repo, or is not pinned to a 40-hex
    commit hash.
    """
    entry = manifest.get_asset(asset_name)
    if entry is None:
        raise UnpinnedModelRevisionError(
            f"model asset {asset_name!r} is not registered, so its Hugging Face revision "
            f"cannot be pinned; register it in the asset manifest before loading {expected_repo!r}"
        )
    if entry.installer != "hf":
        raise UnpinnedModelRevisionError(
            f"model asset {asset_name!r} has installer={entry.installer!r}; only installer='hf' "
            "entries carry a validated commit pin for a Hugging Face load"
        )
    repo = str(entry.hf_repo or "")
    if repo != expected_repo:
        raise UnpinnedModelRevisionError(
            f"model asset {asset_name!r} is registered for repo {repo!r} but the runtime load "
            f"requested {expected_repo!r}; the registry is the single source of truth"
        )
    revision = str(entry.hf_revision or "")
    if not _COMMIT_HASH_RE.match(revision):
        raise UnpinnedModelRevisionError(
            f"model asset {asset_name!r} revision {revision!r} is not an immutable 40-hex commit "
            "hash; a branch/tag is a MOVING target and must not be loaded at run time"
        )
    return repo, revision


def _import_fetch_config() -> type[Any] | None:
    """SpeechBrain >= 1.1.0's ``utils.fetching.FetchConfig`` class, else ``None``.

    A VERSION PROBE, not a feature switch: SpeechBrain moved every fetch control
    (revision, allow_network, token, cache dir) out of ``from_hparams``'s explicit
    parameters and into a ``FetchConfig`` dataclass in 1.1.0. Its presence is the
    signal for which pin SHAPE :func:`pinned_fetch_kwargs` must emit.
    """
    try:
        from speechbrain.utils.fetching import FetchConfig  # noqa: PLC0415 - version probe
    except ImportError:
        return None
    return FetchConfig


def pinned_fetch_kwargs(revision: str, fetch_config_cls: type[Any] | None) -> dict[str, Any]:
    """``from_hparams`` kwargs that pin the load to ``revision``, per API version.

    * SpeechBrain **1.0.x** — ``from_hparams(..., revision=<commit>)``; the explicit
      parameter is forwarded to the ``fetch`` of ``hyperparams.yaml`` AND of
      ``custom.py``, the two artifacts that execute code at load time.
    * SpeechBrain **1.1.0+** — ``from_hparams(..., fetch_config=FetchConfig(revision=...))``.
      There the config reaches BOTH that fetch and ``pretrainer.collect_files``, so
      the checkpoint tensors are pinned too (a strictly wider pin than 1.0.x).

    The shape is NOT interchangeable: on 1.1.0 a bare ``revision=`` falls into
    ``pretrained_from_hparams``'s ``**kwargs``, which are handed to the class
    constructor — and ``Pretrained.__init__(self, modules, hparams, run_opts,
    freeze_params)`` takes no ``**kwargs``, so it raises
    ``TypeError: __init__() got an unexpected keyword argument 'revision'``
    instead of pinning anything. ``sidecar/pyproject.toml`` pins
    ``speechbrain==1.1.0``, so emitting the 1.0.x shape unconditionally would
    break the diarizer outright; ``fetch_config_cls`` is injected (rather than
    probed inside) so both shapes stay unit-testable on either installed version.
    """
    if fetch_config_cls is None:
        return {"revision": revision}
    return {"fetch_config": fetch_config_cls(revision=revision)}


def _import_speechbrain() -> tuple[type[Any], type[Any]]:
    """Import the SpeechBrain inference API ``(VAD, EncoderClassifier)`` — or fail loud.

    Wraps the two ``speechbrain.inference`` imports in a typed guard: a missing
    (or broken) ``speechbrain`` raises :class:`DiarizeBackendUnavailableError`
    with an actionable "install speechbrain / provision the diarizer" message,
    rather than a raw :class:`ModuleNotFoundError` propagating from a job thread.
    Kept a module-level seam (not inside the ``# pragma: no cover`` class body) so
    the fail-loud contract is unit-covered without the heavy native stack. The
    ``speechbrain.inference`` API requires speechbrain >= 1.0.0.
    """
    try:
        from speechbrain.inference.classifiers import EncoderClassifier  # noqa: PLC0415
        from speechbrain.inference.VAD import VAD  # noqa: PLC0415
    except ImportError as exc:
        raise DiarizeBackendUnavailableError(
            "speaker diarization requires SpeechBrain (the VAD + ECAPA backend), "
            "but importing 'speechbrain' failed; install speechbrain "
            '(pip install "media-studio-sidecar[reframe-gpu]") or provision the '
            "diarizer env to enable multi-speaker reframe / diarization"
        ) from exc
    return VAD, EncoderClassifier


def _fetch_safe_audio_path(audio_path: str) -> str:
    """Return ``audio_path`` in a form SpeechBrain's ``fetch`` handles on any OS.

    ``VAD.get_speech_segments`` funnels the audio path through SpeechBrain's
    ``split_path`` + ``fetch`` (HF-fetch machinery keyed on a POSIX ``source/name``
    split). A Windows absolute path (``C:\\dir\\a.wav``) contains no ``/``, so
    ``split_path`` cannot separate the directory from the filename — ``fetch`` then
    treats the whole thing as a bare name and PREPENDS the CWD, yielding a doubled
    path (``…\\cwd\\C:\\dir\\a.wav``) that libsndfile/soundfile cannot open. Forward-
    slashing the path (a no-op on POSIX, whose separators are already ``/``) lets
    ``split_path`` find the final component so ``fetch`` resolves the real file. This
    is what makes the diarize stage runnable on native Windows, not only Linux/WSL.
    """
    return str(audio_path).replace("\\", "/")


class SpeechBrainDiarizer:  # pragma: no cover - requires the heavy native stack
    """VAD + ECAPA pipeline over the pretrained SpeechBrain models.

    Constructed lazily per job (``settings`` selects the device). Both pretrained
    models are loaded on first :meth:`detect_and_embed` so construction stays
    cheap and an import failure surfaces as the job's error (A6 lesson 3).
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._vad: Any = None
        self._encoder: Any = None

    def _device(self) -> str:
        """Prefer CUDA, fall back to CPU (mirrors transcribe's policy)."""
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path (still works)
            return "cpu"

    def _ensure_models(self) -> None:
        if self._vad is not None and self._encoder is not None:
            return
        # Fail loud (typed) when speechbrain is missing — never a raw
        # ModuleNotFoundError out of the job thread (v1.2.0 NO-SILENT-FALLBACK).
        vad_cls, encoder_cls = _import_speechbrain()
        # WU-S5: repo AND revision come from the asset registry (the same pin
        # ``assets.ensure`` snapshot-downloaded), never from a hardcoded repo id
        # at a floating ref. Resolved BEFORE the device probe so a broken pin
        # fails closed without touching CUDA.
        vad_repo, vad_revision = resolve_pinned_hf_source(VAD_ASSET_NAME, VAD_HF_REPO)
        ecapa_repo, ecapa_revision = resolve_pinned_hf_source(ECAPA_ASSET_NAME, ECAPA_HF_REPO)
        # The pin's kwarg SHAPE depends on the installed SpeechBrain (1.0.x
        # ``revision=`` vs 1.1.0+ ``fetch_config=``) — see pinned_fetch_kwargs.
        fetch_config_cls = _import_fetch_config()
        device = self._device()
        run_opts = {"device": device}
        self._vad = vad_cls.from_hparams(
            source=vad_repo, run_opts=run_opts, **pinned_fetch_kwargs(vad_revision, fetch_config_cls)
        )
        self._encoder = encoder_cls.from_hparams(
            source=ecapa_repo, run_opts=run_opts, **pinned_fetch_kwargs(ecapa_revision, fetch_config_cls)
        )
        log.info("speechbrain diarizer ready on %s (pinned %s / %s)", device, vad_revision[:12], ecapa_revision[:12])

    @staticmethod
    def _windows(boundaries: Any) -> list[tuple[float, float]]:
        """Slide a fixed window across each VAD region -> sub-segment spans.

        VAD detects speech, not speaker turns, so each speech region may span
        several speakers. Stepping a ``WINDOW_SEC`` window by ``HOP_SEC`` across
        every region yields time-resolved spans the clustering can tell apart;
        a trailing window shorter than ``MIN_WINDOW_SEC`` is dropped.
        """
        windows: list[tuple[float, float]] = []
        for row in boundaries:
            start = float(row[0])
            end = float(row[1])
            ws = start
            while ws < end:
                we = min(ws + WINDOW_SEC, end)
                if we - ws >= MIN_WINDOW_SEC:
                    windows.append((ws, we))
                if we >= end:
                    break
                ws += HOP_SEC
        return windows

    def detect_and_embed(
        self,
        audio_path: str,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> tuple[list[dict[str, Any]], list[list[float]]]:
        """Run VAD, sub-segment each speech region, then embed each window.

        Returns ``(regions, embeddings)`` 1:1 in time order — exactly what
        ``diarize.diarize_transcript`` consumes. Each VAD speech region is sliced
        into overlapping fixed windows (see :meth:`_windows`) so the embeddings
        are time-resolved and the clustering can separate speakers within one
        continuous-speech region. Progress is reported across the embedding loop;
        ``should_cancel`` is polled per window.
        """
        import torch  # noqa: PLC0415
        import torchaudio  # noqa: PLC0415

        self._ensure_models()
        if on_progress is not None:
            on_progress(5.0, "running VAD")

        # VAD -> a tensor of [start, end] (seconds) speech boundaries. Feed the
        # path forward-slashed so SpeechBrain's split_path/fetch resolves it on
        # Windows too (see _fetch_safe_audio_path), not only POSIX/WSL.
        boundaries = self._vad.get_speech_segments(_fetch_safe_audio_path(audio_path))
        waveform, sr = torchaudio.load(audio_path)
        if sr != TARGET_SR:
            waveform = torchaudio.functional.resample(waveform, sr, TARGET_SR)
            sr = TARGET_SR
        if waveform.shape[0] > 1:  # downmix to mono
            waveform = waveform.mean(dim=0, keepdim=True)

        windows = self._windows(boundaries)
        regions: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        total = max(len(windows), 1)
        for idx, (start, end) in enumerate(windows):
            if should_cancel is not None and should_cancel():
                break
            a = int(start * sr)
            b = int(end * sr)
            chunk = waveform[:, a:b]
            if chunk.shape[1] <= 0:
                continue
            with torch.no_grad():
                emb = self._encoder.encode_batch(chunk)
            vec = emb.squeeze().detach().cpu().tolist()
            if isinstance(vec, float):  # 1-D degenerate guard
                vec = [vec]
            regions.append({"start": start, "end": end})
            embeddings.append([float(x) for x in vec])
            if on_progress is not None:
                on_progress(5.0 + (idx + 1) / total * 75.0, f"embedding window {idx + 1}/{total}")
        return regions, embeddings


__all__ = [
    "HOP_SEC",
    "MIN_WINDOW_SEC",
    "SUBWINDOW_CLUSTER_THRESHOLD",
    "TARGET_SR",
    "WINDOW_SEC",
    "DiarizeBackendUnavailableError",
    "SpeechBrainDiarizer",
    "UnpinnedModelRevisionError",
    "pinned_fetch_kwargs",
    "resolve_pinned_hf_source",
]
