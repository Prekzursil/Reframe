"""OPT-IN pyannote.audio 3.1 speaker-diarization backend (Phase 8 WU / Decision #3).

This is a SECOND diarization backend that plugs into the EXISTING
:class:`media_studio.features.diarize.DiarizerBackend` seam — the same
``detect_and_embed(audio_path) -> (regions, embeddings)`` contract the default
SpeechBrain backend (``diarize_backend.SpeechBrainDiarizer``) implements. The
pure clustering / label-stamping in ``diarize.py`` is reused UNCHANGED; this
module only supplies an alternative *heavy* backend the Integrate phase can
select via ``settings['diarizeBackend'] == 'pyannote'``.

Why opt-in (and off by default):

* The pyannote 3.1 pipeline (``pyannote/speaker-diarization-3.1``) and its
  dependency (``pyannote/segmentation-3.0``) are **gated** HF repos: the user
  must accept the terms on BOTH and provide an HF access token. We read that
  token from the environment (``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN`` — the two
  names huggingface_hub itself honours), per the locked Decision #3.
* The weights are MIT-licensed (commercial OK) but ~1.6 GB across two repos and
  require ``torch``; the default speaker path stays SpeechBrain unless the user
  explicitly switches.

Layering (mirrors ``diarize_backend.py``):

* The HEAVY half — the ``pyannote.audio`` / ``torch`` import and pipeline run —
  lives inside :class:`PyannoteDiarizer.detect_and_embed`, which is
  ``# pragma: no cover`` (it needs the native stack + real audio + gated weights,
  none of which are in the test venv).
* The LIGHT half — token resolution, asset registration, installed-state probing,
  the backend-factory selector, and the pure pyannote-annotation -> (regions,
  embeddings) converter — is plain stdlib/dict logic, fully unit-tested with
  hand-built fakes (no model, no audio, no token).

The Integrate phase wires this in by passing :func:`select_backend_factory` (or a
closure over it) as ``diarize.register(..., backend_factory=...)`` and registering
the two gated assets via :func:`register_pyannote_assets`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..assets import manifest
from ..protocol import ErrorCode, RpcError
from ..util import get_logger
from .diarize import CancelProbe, DiarizerBackend, ProgressCb

log = get_logger("media_studio.features.pyannote_backend")

# --------------------------------------------------------------------------- #
# the gated assets (BOTH required) — PINNED (A6 lesson 5)
# --------------------------------------------------------------------------- #
#: the diarization PIPELINE repo (gated). 3.1 = pure-PyTorch, no onnxruntime.
PIPELINE_ASSET_NAME = "pyannote-speaker-diarization-31"
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-3.1"
# F3c: pin the HF snapshot revisions to commit hashes (verified 2026-06-28).
PYANNOTE_PIPELINE_REVISION = "84fd25912480287da0247647c3d2b4853cb3ee5d"
PIPELINE_SIZE_MB = 1000

#: the SEGMENTATION dependency repo (also gated — both terms must be accepted).
SEGMENTATION_ASSET_NAME = "pyannote-segmentation-30"
PYANNOTE_SEGMENTATION = "pyannote/segmentation-3.0"
PYANNOTE_SEGMENTATION_REVISION = "e66f3d3b9eb0873085418a7b813d3b369bf160bb"
SEGMENTATION_SIZE_MB = 600

#: both gated assets must be present before pyannote diarization can run.
REQUIRED_ASSETS: tuple[str, ...] = (PIPELINE_ASSET_NAME, SEGMENTATION_ASSET_NAME)

#: the env var names huggingface_hub honours, in priority order. The first
#: non-empty one wins (``HF_TOKEN`` is the modern canonical name).
HF_TOKEN_ENV_VARS: tuple[str, ...] = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")

#: the settings value that selects this backend over the default speechbrain one.
BACKEND_KEY = "diarizeBackend"
PYANNOTE_BACKEND = "pyannote"
SPEECHBRAIN_BACKEND = "speechbrain"

#: pyannote runs at 16 kHz mono (same as the speechbrain path).
TARGET_SR = 16000


class PyannoteConfigError(RpcError):
    """Typed refusal when pyannote is selected but cannot be configured.

    Subclasses :class:`RpcError` (INVALID_PARAMS) so the message — e.g. "no HF
    token" — reaches the UI verbatim through the normal error channel rather than
    surfacing as a stack trace deep inside the heavy stack (A6 lesson 3).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.INVALID_PARAMS)


# --------------------------------------------------------------------------- #
# pure/light: HF token resolution (Decision #3)
# --------------------------------------------------------------------------- #
def resolve_hf_token(env: Mapping[str, str] | None = None) -> str | None:
    """Return the HF access token from the environment, or ``None``.

    Reads ``HF_TOKEN`` then ``HUGGING_FACE_HUB_TOKEN`` (the two names
    huggingface_hub itself honours). Whitespace-only values count as absent so a
    blank export does not masquerade as a real token. ``env`` is injectable so
    tests never touch ``os.environ``.
    """
    env_map = env if env is not None else os.environ
    for name in HF_TOKEN_ENV_VARS:
        value = env_map.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def require_hf_token(env: Mapping[str, str] | None = None) -> str:
    """Like :func:`resolve_hf_token` but raise :class:`PyannoteConfigError`.

    Used on the run path: pyannote's gated weights cannot be fetched (or, for an
    already-cached snapshot, loaded by the gated pipeline) without a token, so an
    absent one is a clean, actionable refusal rather than a deep HF 401.
    """
    token = resolve_hf_token(env)
    if not token:
        joined = " or ".join(HF_TOKEN_ENV_VARS)
        raise PyannoteConfigError(
            f"pyannote diarization needs a Hugging Face access token — set {joined} in the "
            "environment and accept the terms on both gated repos "
            f"({PYANNOTE_PIPELINE} and {PYANNOTE_SEGMENTATION})."
        )
    return token


# --------------------------------------------------------------------------- #
# pure/light: installed-state probe (drives the offline gate, like diarize)
# --------------------------------------------------------------------------- #
def default_models_present(settings: dict[str, Any]) -> bool:
    """True when BOTH gated pyannote assets are installed locally (no import).

    Uses the asset manager's installed-detection so an already-cached HF snapshot
    counts — that is what lets pyannote diarization run offline once the gated
    repos have been fetched. Mirrors ``diarize.default_models_present``.
    """
    from ..assets.manager import AssetManager  # noqa: PLC0415 - lazy: avoids a cycle

    mgr = AssetManager(settings_provider=lambda: settings)
    for name in REQUIRED_ASSETS:
        entry = manifest.get_asset(name)
        if entry is None or mgr.installed_path(entry) is None:
            return False
    return True


# --------------------------------------------------------------------------- #
# pure/light: pyannote Annotation -> (regions, embeddings) converter
# --------------------------------------------------------------------------- #
def regions_and_embeddings(
    spans: Sequence[Mapping[str, Any]],
    embeddings: Sequence[Sequence[float]],
) -> tuple[list[dict[str, Any]], list[list[float]]]:
    """Normalize the heavy backend's raw output into the diarize seam shape.

    ``spans`` are ``{start, end}`` speech windows (one per pyannote segment) and
    ``embeddings`` are their speaker-embedding vectors, 1:1 in time order. The
    return is exactly what ``diarize.diarize_transcript`` consumes:
    ``(regions, embeddings)`` with ``regions[i] = {"start": .., "end": ..}`` and
    float-coerced vectors. Length mismatch is a programming error -> ``ValueError``
    (kept pure so the heavy path stays a thin shim over this).
    """
    if len(spans) != len(embeddings):
        raise ValueError(f"spans/embeddings length mismatch: {len(spans)} spans vs {len(embeddings)} embeddings")
    regions: list[dict[str, Any]] = []
    vecs: list[list[float]] = []
    for span, vec in zip(spans, embeddings, strict=True):
        regions.append({"start": float(span.get("start", 0.0)), "end": float(span.get("end", 0.0))})
        vecs.append([float(x) for x in vec])
    return regions, vecs


# --------------------------------------------------------------------------- #
# the heavy backend (conforms to diarize.DiarizerBackend) — pragma'd
# --------------------------------------------------------------------------- #
class PyannoteDiarizer:  # pragma: no cover - requires the heavy native stack + gated weights
    """pyannote.audio 3.1 diarization conforming to ``diarize.DiarizerBackend``.

    Constructed lazily per job; ``settings`` selects the device + ASR options. The
    ``pyannote.audio`` / ``torch`` imports live INSIDE :meth:`detect_and_embed`
    (run-time only), and the gated pipeline is loaded with the env HF token. The
    raw pipeline output is funnelled through the pure :func:`regions_and_embeddings`
    so the clustering in ``diarize.py`` (greedy cosine) drives the final labels —
    pyannote here supplies high-quality per-segment speaker embeddings, not its
    own clustering, keeping ONE labelling code path across both backends.
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = dict(settings or {})
        self._env = dict(env if env is not None else os.environ)
        self._pipeline: Any = None
        # Fail fast (typed) if no token — before any heavy import.
        self._token = require_hf_token(self._env)

    def _device(self) -> str:
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path
            return "cpu"

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        import torch  # noqa: PLC0415
        from pyannote.audio import Pipeline  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, use_auth_token=self._token)
        pipeline.to(torch.device(self._device()))
        self._pipeline = pipeline
        log.info("pyannote diarizer ready on %s", self._device())

    def detect_and_embed(
        self,
        audio_path: str,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> tuple[list[dict[str, Any]], list[list[float]]]:
        """Run the pyannote pipeline; return ``(regions, embeddings)`` in time order."""
        self._ensure_pipeline()
        if on_progress is not None:
            on_progress(5.0, "running pyannote diarization")
        diarization, raw_embeddings = self._pipeline(audio_path, return_embeddings=True)

        spans: list[dict[str, Any]] = []
        vecs: list[Sequence[float]] = []
        tracks = list(diarization.itertracks(yield_label=True))
        total = max(len(tracks), 1)
        speaker_order: dict[str, int] = {}
        for idx, (segment, _track, label) in enumerate(tracks):
            if should_cancel is not None and should_cancel():
                break
            row = speaker_order.setdefault(label, len(speaker_order))
            spans.append({"start": float(segment.start), "end": float(segment.end)})
            vecs.append([float(x) for x in raw_embeddings[row]])
            if on_progress is not None:
                on_progress(5.0 + (idx + 1) / total * 75.0, f"segment {idx + 1}/{total}")
        return regions_and_embeddings(spans, vecs)


# --------------------------------------------------------------------------- #
# the factory seam + the backend selector (what the Integrate phase wires in)
# --------------------------------------------------------------------------- #
def pyannote_backend_factory(settings: dict[str, Any]) -> DiarizerBackend:
    """Build the real pyannote backend (validates the token eagerly).

    Token resolution + the typed refusal happen HERE (light, tested); the heavy
    ``pyannote.audio`` import is deferred to first use inside the returned object.
    """
    return PyannoteDiarizer(settings)


def selected_backend_name(settings: Mapping[str, Any] | None) -> str:
    """The chosen diarize backend name from settings, defaulting to speechbrain.

    Any value other than ``"pyannote"`` resolves to ``"speechbrain"`` so an
    unknown/typo'd setting never silently breaks diarization — it just keeps the
    safe default backend.
    """
    settings = settings or {}
    value = settings.get(BACKEND_KEY)
    if isinstance(value, str) and value.strip().lower() == PYANNOTE_BACKEND:
        return PYANNOTE_BACKEND
    return SPEECHBRAIN_BACKEND


def select_backend_factory(
    settings: dict[str, Any],
    *,
    speechbrain_factory: Callable[[dict[str, Any]], DiarizerBackend],
    pyannote_factory: Callable[[dict[str, Any]], DiarizerBackend] | None = None,
) -> DiarizerBackend:
    """Pick + build the diarizer backend per ``settings['diarizeBackend']``.

    The Integrate phase passes this (closed over the two factories) as
    ``diarize.register(backend_factory=...)``. When pyannote is selected, this
    validates the HF token via the pyannote factory (raising
    :class:`PyannoteConfigError` if absent) BEFORE any heavy import; otherwise it
    builds the default speechbrain backend, unchanged.
    """
    if selected_backend_name(settings) == PYANNOTE_BACKEND:
        factory = pyannote_factory if pyannote_factory is not None else pyannote_backend_factory
        return factory(settings)
    return speechbrain_factory(settings)


# --------------------------------------------------------------------------- #
# asset registration (BOTH gated repos; HF-token-driven at install time)
# --------------------------------------------------------------------------- #
def register_pyannote_assets() -> None:
    """Register the two gated pyannote models as on-demand assets (idempotent).

    Both ``speaker-diarization-3.1`` and ``segmentation-3.0`` are gated HF repos;
    the asset manager reads the HF token from the env (``HF_TOKEN`` /
    ``HUGGING_FACE_HUB_TOKEN``) when fetching them. Re-registering identical
    entries is a no-op (module re-import safe).
    """
    manifest.register_asset(
        manifest.AssetEntry(
            name=PIPELINE_ASSET_NAME,
            kind="model",
            size_mb=PIPELINE_SIZE_MB,
            label="pyannote speaker-diarization 3.1 (gated, HF token)",
            installer="hf",
            hf_repo=PYANNOTE_PIPELINE,
            hf_revision=PYANNOTE_PIPELINE_REVISION,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=SEGMENTATION_ASSET_NAME,
            kind="model",
            size_mb=SEGMENTATION_SIZE_MB,
            label="pyannote segmentation 3.0 (gated, HF token; required by 3.1)",
            installer="hf",
            hf_repo=PYANNOTE_SEGMENTATION,
            hf_revision=PYANNOTE_SEGMENTATION_REVISION,
        )
    )


# Register the assets at import (mirrors diarize.register_diarize_assets()).
register_pyannote_assets()


__all__ = [
    "BACKEND_KEY",
    "HF_TOKEN_ENV_VARS",
    "PIPELINE_ASSET_NAME",
    "PYANNOTE_BACKEND",
    "PYANNOTE_PIPELINE",
    "PYANNOTE_SEGMENTATION",
    "REQUIRED_ASSETS",
    "SEGMENTATION_ASSET_NAME",
    "SPEECHBRAIN_BACKEND",
    "TARGET_SR",
    "PyannoteConfigError",
    "PyannoteDiarizer",
    "default_models_present",
    "pyannote_backend_factory",
    "regions_and_embeddings",
    "register_pyannote_assets",
    "require_hf_token",
    "resolve_hf_token",
    "select_backend_factory",
    "selected_backend_name",
]
