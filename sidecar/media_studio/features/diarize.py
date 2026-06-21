"""Token-free speaker DIARIZATION (this group's feature 4).

Pipeline (all local, no API token):

    SpeechBrain VAD  ->  ECAPA-TDNN embeddings per speech region
                     ->  greedy cosine clustering (a new speaker whenever the
                         nearest existing centroid is below a threshold)
                     ->  SPEAKER_NN labels stamped onto the transcript segments.

The result is a §3 transcript with a ``speaker`` field on each segment (and a
``speakers`` roster), produced WITHOUT any cloud call or token — purely from the
two SpeechBrain models, which are **on-demand assets** (registered in the U4
manifest so ``assets.ensure`` downloads them; gated behind an offline refusal).

The heavy half is behind a single **loader seam** (:class:`DiarizerBackend`):
this module — and its tests — never import speechbrain / torch at import time.
The PURE half — greedy cosine clustering, label formatting, stamping labels onto
a transcript — is plain math/dicts and is fully unit-tested with hand-built
embeddings (no model, no audio).

Offline behaviour (the brief's "offline-refuses-gated-models"): the models are
gated assets. ``diarize.start`` refuses with a typed :class:`OfflineError` when
offline mode is on AND the models are not already present locally — a download
would need the network. If the models ARE already installed, diarization runs
offline (the whole point of local diarization). ``guard`` is the single seam
deciding "may I fetch a missing model right now?".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from .. import protocol
from ..assets import manifest
from ..protocol import ErrorCode, RpcContext, RpcError
from ..settings_store import default_config_dir
from ..util import clamp, get_logger
from . import offline as _offline

log = get_logger("media_studio.features.diarize")

Transcript = dict[str, Any]
Segment = dict[str, Any]
Embedding = Sequence[float]

#: cosine SIMILARITY threshold: a region whose best-match centroid similarity is
#: below this opens a NEW speaker. Tuned conservative (ECAPA same-speaker pairs
#: typically score > 0.5; cross-speaker < 0.3). Overridable per call.
DEFAULT_THRESHOLD = 0.5

#: a cooperative cancel probe + a progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]

# --------------------------------------------------------------------------- #
# on-demand assets (U4 manifest entries; HF installer like whisper)
# --------------------------------------------------------------------------- #
VAD_ASSET_NAME = "speechbrain-vad-crdnn"
VAD_HF_REPO = "speechbrain/vad-crdnn-libriparty"
VAD_SIZE_MB = 70

ECAPA_ASSET_NAME = "speechbrain-ecapa-voxceleb"
ECAPA_HF_REPO = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_SIZE_MB = 80

#: the asset names diarization needs present before it can run.
REQUIRED_ASSETS: tuple[str, ...] = (VAD_ASSET_NAME, ECAPA_ASSET_NAME)


# --------------------------------------------------------------------------- #
# pure: cosine math + greedy clustering + label stamping
# --------------------------------------------------------------------------- #
def cosine_similarity(a: Embedding, b: Embedding) -> float:
    """Cosine similarity of two equal-length vectors (0.0 for a zero vector)."""
    if len(a) != len(b):
        raise ValueError(f"embedding length mismatch: {len(a)} vs {len(b)}")
    dot = sum(float(x) * float(y) for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _add_into(acc: list[float], vec: Embedding) -> list[float]:
    """Element-wise add ``vec`` into a running sum (for incremental centroids)."""
    return [a + float(v) for a, v in zip(acc, vec, strict=True)]


def greedy_cluster(
    embeddings: Sequence[Embedding],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[int]:
    """Greedy cosine clustering -> a cluster index per embedding (in order).

    Walks the embeddings in time order; each is assigned to the existing cluster
    whose **centroid** is most cosine-similar, opening a NEW cluster when even
    the best similarity is below ``threshold``. Centroids are the running MEAN of
    their members (kept as sum + count for an exact incremental mean). The first
    embedding always starts cluster 0. Deterministic; O(n·k).
    """
    labels: list[int] = []
    sums: list[list[float]] = []
    counts: list[int] = []
    for vec in embeddings:
        vec_list = [float(v) for v in vec]
        best_idx = -1
        best_sim = -1.0
        for idx, (s, c) in enumerate(zip(sums, counts, strict=True)):
            centroid = [v / c for v in s]
            sim = cosine_similarity(vec_list, centroid)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
        if best_idx < 0 or best_sim < threshold:
            sums.append(list(vec_list))
            counts.append(1)
            labels.append(len(sums) - 1)
        else:
            sums[best_idx] = _add_into(sums[best_idx], vec_list)
            counts[best_idx] += 1
            labels.append(best_idx)
    return labels


def speaker_label(index: int) -> str:
    """Format a cluster index as a SPEAKER_NN label (0 -> SPEAKER_00)."""
    return f"SPEAKER_{int(index):02d}"


def assign_speakers_to_segments(
    segments: Sequence[Segment],
    regions: Sequence[dict[str, Any]],
    cluster_labels: Sequence[int],
) -> list[Segment]:
    """Stamp a ``speaker`` label onto each segment (immutable copies).

    ``regions`` are the diarized speech windows ``{start, end}`` each carrying
    one ``cluster_labels`` entry; a segment gets the speaker of the region with
    the greatest TEMPORAL OVERLAP (its mid-point's region if none overlaps).
    Segments with no region match keep ``speaker = ""``. Returns new dicts — the
    input segments are never mutated (coding-style: immutability).
    """
    region_spans = [
        (float(r.get("start", 0.0)), float(r.get("end", 0.0)), speaker_label(cluster_labels[i]))
        for i, r in enumerate(regions)
        if i < len(cluster_labels)
    ]
    out: list[Segment] = []
    for seg in segments:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        best_label = ""
        best_overlap = 0.0
        for r_start, r_end, label in region_spans:
            overlap = min(s_end, r_end) - max(s_start, r_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = label
        if not best_label and region_spans:
            mid = (s_start + s_end) / 2.0
            # nearest region by mid-point distance to its span
            best_label = min(
                region_spans,
                key=lambda rs: 0.0 if rs[0] <= mid <= rs[1] else min(abs(mid - rs[0]), abs(mid - rs[1])),
            )[2]
        out.append({**seg, "speaker": best_label})
    return out


def roster(cluster_labels: Sequence[int]) -> list[str]:
    """The sorted, de-duplicated SPEAKER_NN roster for a clustering."""
    return [speaker_label(i) for i in sorted({int(c) for c in cluster_labels})]


def rename_speakers(transcript: Transcript, mapping: dict[str, str]) -> Transcript:
    """Rewrite speaker labels in a transcript via ``mapping`` (immutable).

    ``mapping`` is ``{SPEAKER_NN: friendly}``. Every segment's ``speaker`` and the
    top-level ``speakers`` roster are rewritten through it; labels not in the
    mapping pass through unchanged. Returns a NEW transcript dict — the input is
    never mutated (mirrors :func:`assign_speakers_to_segments`). Segments without
    a ``speaker`` key are left as-is (no key is added).
    """
    segments: list[Segment] = []
    for seg in transcript.get("segments") or []:
        if "speaker" in seg:
            segments.append({**seg, "speaker": mapping.get(seg["speaker"], seg["speaker"])})
        else:
            segments.append({**seg})
    speakers = [mapping.get(s, s) for s in transcript.get("speakers") or []]
    return {**transcript, "segments": segments, "speakers": speakers}


def diarize_transcript(
    transcript: Transcript,
    regions: Sequence[dict[str, Any]],
    embeddings: Sequence[Embedding],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> Transcript:
    """Pure end-to-end: cluster ``embeddings`` -> stamp speakers on a transcript.

    Returns a NEW transcript dict with ``speaker`` on every segment and a
    top-level ``speakers`` roster. ``regions`` + ``embeddings`` are 1:1 and in
    time order (the backend produces them together). When the lists are empty
    (silence-only audio), the transcript is returned with empty speaker labels.
    """
    if not embeddings:
        segments = [{**seg, "speaker": ""} for seg in transcript.get("segments") or []]
        return {**transcript, "segments": segments, "speakers": []}
    labels = greedy_cluster(embeddings, threshold=threshold)
    segments = assign_speakers_to_segments(transcript.get("segments") or [], regions, labels)
    return {**transcript, "segments": segments, "speakers": roster(labels)}


# --------------------------------------------------------------------------- #
# the heavy backend seam (speechbrain VAD + ECAPA) — never imported here
# --------------------------------------------------------------------------- #
class DiarizerBackend(Protocol):
    """The slice of the SpeechBrain pipeline the runner needs.

    A real implementation (constructed lazily, never at import time) runs VAD to
    get speech ``regions`` and ECAPA to embed each. Tests inject a fake that
    returns hand-built regions + embeddings, so no model/audio is touched.
    """

    def detect_and_embed(
        self,
        audio_path: str,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> tuple[list[dict[str, Any]], list[list[float]]]:
        """Return ``(regions, embeddings)`` — speech windows + their ECAPA vecs."""
        ...  # pragma: no cover


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class Diarize:
    """Owns ``diarize.start`` over injectable seams.

    Seams: ``resolver`` (videoId -> path), ``load_project`` / ``save_project``
    (the transcript store), ``settings_provider`` (offline + threshold),
    ``backend_factory`` (builds the heavy :class:`DiarizerBackend`, lazily), and
    ``models_present`` (are the gated assets installed? — drives the offline
    refusal). The pure clustering is reused as-is.
    """

    def __init__(
        self,
        *,
        resolver: Callable[[str], str | None],
        load_project: Callable[[str], dict[str, Any]],
        save_project: Callable[[str, dict[str, Any]], None],
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        backend_factory: Callable[[dict[str, Any]], DiarizerBackend] | None = None,
        models_present: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self._resolver = resolver
        self._load_project = load_project
        self._save_project = save_project
        self._settings_provider = settings_provider or (lambda: {})
        self._backend_factory = backend_factory or _default_backend_factory
        self._models_present = models_present or default_models_present

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - never crash the handler on settings
            return {}

    def start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``diarize.start({videoId, threshold?})`` -> ``{jobId}`` (long job).

        ``job.done.result`` = ``{transcript}`` (the persisted, speaker-labelled
        transcript). Refuses with :class:`OfflineError` when offline AND the
        gated models are missing (a download would need the network); runs
        normally offline when they are already installed.
        """
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            raise RpcError("videoId (str) is required", ErrorCode.INVALID_PARAMS)
        threshold = params.get("threshold")
        if threshold is not None and not isinstance(threshold, (int, float)):
            raise RpcError("threshold must be a number when given", ErrorCode.INVALID_PARAMS)
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)

        settings = self._settings()
        audio_path = self._resolver(video_id)
        if not audio_path:
            raise RpcError(f"unknown video: {video_id}", ErrorCode.INVALID_PARAMS)
        project = self._load_project(video_id)
        transcript = project.get("transcript")
        if not transcript:
            raise RpcError(
                f"video {video_id} has no transcript yet (run transcribe.start first)",
                ErrorCode.INVALID_PARAMS,
            )

        # Offline gate: only the network path (a missing-model download) is
        # refused. Installed models -> diarize offline, no refusal.
        if not self._models_present(settings):
            _offline.guard_network(
                settings,
                "downloading the SpeechBrain diarization models (VAD + ECAPA)",
            )

        thr = float(threshold) if threshold is not None else DEFAULT_THRESHOLD
        backend_factory = self._backend_factory

        def job_body(job_ctx: Any) -> dict[str, Any]:
            backend = backend_factory(settings)
            job_ctx.progress(2.0, "detecting speech regions")
            regions, embeddings = backend.detect_and_embed(
                audio_path,
                on_progress=lambda pct, msg: job_ctx.progress(clamp(pct, 0.0, 80.0), msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            job_ctx.raise_if_cancelled()
            job_ctx.progress(85.0, "clustering speakers")
            labelled = diarize_transcript(transcript, regions, embeddings, threshold=thr)
            if not job_ctx.cancelled:
                fresh = self._load_project(video_id)
                fresh["transcript"] = labelled
                self._save_project(video_id, fresh)
            job_ctx.progress(100.0, "done")
            return {"transcript": labelled}

        job = ctx.jobs.start(job_body, feature="diarize", label="diarize", videoId=video_id, gpu=True)
        return {"jobId": job.id}

    def rename(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``diarize.rename({videoId, mapping})`` -> ``{transcript}`` (direct).

        Applies ``mapping`` (``{SPEAKER_NN: friendly}``) to the persisted
        transcript via the pure :func:`rename_speakers`, saves it back onto a
        fresh project load (so unrelated fields are preserved), and returns the
        renamed transcript. Direct return — not a job.
        """
        del ctx  # no jobs/notifications needed for this synchronous rename
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            raise RpcError("videoId (str) is required", ErrorCode.INVALID_PARAMS)
        mapping = params.get("mapping")
        if not isinstance(mapping, dict):
            raise RpcError("mapping (dict) is required", ErrorCode.INVALID_PARAMS)

        project = self._load_project(video_id)
        transcript = project.get("transcript")
        if not transcript:
            raise RpcError(
                f"video {video_id} has no transcript yet (run diarize.start first)",
                ErrorCode.INVALID_PARAMS,
            )

        renamed = rename_speakers(transcript, {str(k): str(v) for k, v in mapping.items()})
        fresh = self._load_project(video_id)
        fresh["transcript"] = renamed
        self._save_project(video_id, fresh)
        return {"transcript": renamed}


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def default_models_present(settings: dict[str, Any]) -> bool:
    """True when BOTH gated SpeechBrain assets are installed (no import).

    Uses the asset manager's installed-detection so an already-cached HF
    snapshot counts — that is what makes offline diarization possible.
    """
    from ..assets.manager import AssetManager  # noqa: PLC0415 - lazy: avoids a cycle

    mgr = AssetManager(settings_provider=lambda: settings)
    for name in REQUIRED_ASSETS:
        entry = manifest.get_asset(name)
        if entry is None or mgr.installed_path(entry) is None:
            return False
    return True


def _default_backend_factory(settings: dict[str, Any]) -> DiarizerBackend:
    """Build the real speechbrain-backed diarizer (LAZY import; runtime only)."""
    from .diarize_backend import SpeechBrainDiarizer  # noqa: PLC0415 - heavy seam

    return SpeechBrainDiarizer(settings)


def register_diarize_assets() -> None:
    """Register the VAD + ECAPA models as U4 on-demand assets (idempotent)."""
    manifest.register_asset(
        manifest.AssetEntry(
            name=VAD_ASSET_NAME,
            kind="model",
            size_mb=VAD_SIZE_MB,
            label="SpeechBrain VAD (CRDNN, speech detection)",
            installer="hf",
            hf_repo=VAD_HF_REPO,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=ECAPA_ASSET_NAME,
            kind="model",
            size_mb=ECAPA_SIZE_MB,
            label="SpeechBrain ECAPA-TDNN (speaker embeddings)",
            installer="hf",
            hf_repo=ECAPA_HF_REPO,
        )
    )


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Callable[[str], str | None],
    load_project: Callable[[str], dict[str, Any]],
    save_project: Callable[[str, dict[str, Any]], None],
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    backend_factory: Callable[[dict[str, Any]], DiarizerBackend] | None = None,
    models_present: Callable[[dict[str, Any]], bool] | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Diarize:
    """Create a :class:`Diarize` and register ``diarize.start`` (long job).

    Also registers the two gated assets in the manifest. ``register_fn`` defaults
    to :func:`protocol.register`; tests inject a fake registrar + fake seams.
    """
    register_diarize_assets()
    service = Diarize(
        resolver=resolver,
        load_project=load_project,
        save_project=save_project,
        settings_provider=settings_provider,
        backend_factory=backend_factory,
        models_present=models_present,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("diarize.start", service.start)
    reg("diarize.rename", service.rename)
    return service


# Register the assets at import (mirrors tools_resolver / manifest._register_day1).
register_diarize_assets()


def _data_root() -> str:
    """The assets root (kept for symmetry with the other features)."""
    return str(default_config_dir())


__all__ = [
    "DEFAULT_THRESHOLD",
    "ECAPA_ASSET_NAME",
    "REQUIRED_ASSETS",
    "VAD_ASSET_NAME",
    "Diarize",
    "DiarizerBackend",
    "assign_speakers_to_segments",
    "cosine_similarity",
    "default_models_present",
    "diarize_transcript",
    "greedy_cluster",
    "register",
    "register_diarize_assets",
    "rename_speakers",
    "roster",
    "speaker_label",
]
