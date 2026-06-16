"""Tests for media_studio.features.diarize — token-free speaker diarization.

The PURE pipeline (cosine sim, greedy clustering, label stamping, end-to-end
diarize_transcript) is tested with hand-built embeddings — no model, no audio.
The handler is tested with a fake backend + the real JobRegistry, plus the
offline-refuses-gated-models gate. No speechbrain / torch import anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import diarize
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# pure: cosine_similarity
# --------------------------------------------------------------------------- #
class TestCosine:
    def test_identical_vectors(self):
        assert diarize.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert diarize.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite(self):
        assert diarize.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_is_zero(self):
        assert diarize.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            diarize.cosine_similarity([1.0], [1.0, 2.0])


# --------------------------------------------------------------------------- #
# pure: greedy_cluster
# --------------------------------------------------------------------------- #
class TestGreedyCluster:
    def test_two_clear_speakers(self):
        # Two well-separated directions -> two clusters, interleaved correctly.
        embs = [[1.0, 0.0], [0.95, 0.05], [0.0, 1.0], [0.05, 0.95]]
        assert diarize.greedy_cluster(embs, threshold=0.5) == [0, 0, 1, 1]

    def test_single_speaker(self):
        embs = [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02]]
        assert diarize.greedy_cluster(embs) == [0, 0, 0]

    def test_high_threshold_splits_more(self):
        embs = [[1.0, 0.0], [0.7, 0.7]]
        # cos ~0.707 < 0.9 threshold -> a second cluster opens.
        assert diarize.greedy_cluster(embs, threshold=0.9) == [0, 1]

    def test_empty(self):
        assert diarize.greedy_cluster([]) == []

    def test_first_always_cluster_zero(self):
        assert diarize.greedy_cluster([[0.0, 0.0]])[0] == 0

    def test_later_centroid_not_better_keeps_first(self):
        # Three vecs, two clusters; the third matches cluster 0 perfectly, so when
        # the loop checks cluster 1 its similarity is NOT greater than the running
        # best (the `sim > best_sim` false branch) -> assigned back to cluster 0.
        embs = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        assert diarize.greedy_cluster(embs, threshold=0.4) == [0, 1, 0]


# --------------------------------------------------------------------------- #
# pure: speaker_label / roster
# --------------------------------------------------------------------------- #
class TestLabels:
    def test_speaker_label_padding(self):
        assert diarize.speaker_label(0) == "SPEAKER_00"
        assert diarize.speaker_label(7) == "SPEAKER_07"
        assert diarize.speaker_label(12) == "SPEAKER_12"

    def test_roster_sorted_unique(self):
        assert diarize.roster([2, 0, 0, 1, 2]) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


# --------------------------------------------------------------------------- #
# pure: assign_speakers_to_segments
# --------------------------------------------------------------------------- #
class TestAssign:
    def test_overlap_assignment(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 5.0, "end": 6.0, "text": "b"}]
        regions = [{"start": 0.0, "end": 2.0}, {"start": 4.5, "end": 6.5}]
        out = diarize.assign_speakers_to_segments(segs, regions, [0, 1])
        assert out[0]["speaker"] == "SPEAKER_00"
        assert out[1]["speaker"] == "SPEAKER_01"

    def test_does_not_mutate_input(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "a"}]
        diarize.assign_speakers_to_segments(segs, [{"start": 0.0, "end": 1.0}], [0])
        assert "speaker" not in segs[0]  # original untouched

    def test_no_overlap_falls_back_to_nearest(self):
        segs = [{"start": 10.0, "end": 11.0, "text": "x"}]
        regions = [{"start": 0.0, "end": 1.0}, {"start": 8.0, "end": 9.0}]
        out = diarize.assign_speakers_to_segments(segs, regions, [0, 1])
        assert out[0]["speaker"] == "SPEAKER_01"  # the nearer region

    def test_no_regions_leaves_blank(self):
        out = diarize.assign_speakers_to_segments([{"start": 0.0, "end": 1.0}], [], [])
        assert out[0]["speaker"] == ""


# --------------------------------------------------------------------------- #
# pure: diarize_transcript end-to-end
# --------------------------------------------------------------------------- #
class TestDiarizeTranscript:
    def test_full(self):
        transcript = {
            "language": "en",
            "durationSec": 6.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hi"},
                {"start": 5.0, "end": 6.0, "text": "bye"},
            ],
        }
        regions = [{"start": 0.0, "end": 2.0}, {"start": 4.5, "end": 6.0}]
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        out = diarize.diarize_transcript(transcript, regions, embeddings, threshold=0.5)
        assert out["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
        assert out["segments"][0]["speaker"] == "SPEAKER_00"
        assert out["segments"][1]["speaker"] == "SPEAKER_01"
        assert out["language"] == "en"  # untouched fields preserved

    def test_empty_embeddings_blank_speakers(self):
        transcript = {"language": "en", "durationSec": 1.0, "segments": [{"start": 0.0, "end": 1.0}]}
        out = diarize.diarize_transcript(transcript, [], [])
        assert out["speakers"] == []
        assert out["segments"][0]["speaker"] == ""


# --------------------------------------------------------------------------- #
# Diarize.start — the handler
# --------------------------------------------------------------------------- #
class FakeBackend:
    def __init__(self, regions, embeddings):
        self._regions = regions
        self._embeddings = embeddings

    def detect_and_embed(self, audio_path, *, on_progress=None, should_cancel=None):
        if on_progress is not None:
            on_progress(40.0, "embedding")
        return self._regions, self._embeddings


def _registry():
    events: list[tuple] = []
    reg = JobRegistry(
        emit_progress=lambda j, p, m: events.append(("progress", j, p, m)),
        emit_done=lambda j, r: events.append(("done", j, r)),
    )
    return reg, events


def _ctx(reg) -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=reg)


class TestStartHandler:
    def _service(self, project, *, models_present=True, settings=None, saved=None):
        saved = saved if saved is not None else {}

        def save(video_id, data):
            saved[video_id] = data

        return diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=lambda v: dict(project),
            save_project=save,
            settings_provider=lambda: settings or {},
            backend_factory=lambda s: FakeBackend(
                [{"start": 0.0, "end": 2.0}, {"start": 4.5, "end": 6.0}],
                [[1.0, 0.0], [0.0, 1.0]],
            ),
            models_present=lambda s: models_present,
        ), saved

    def _project(self):
        return {
            "transcript": {
                "language": "en",
                "durationSec": 6.0,
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "hi"},
                    {"start": 5.0, "end": 6.0, "text": "bye"},
                ],
            }
        }

    def test_requires_video_id(self):
        reg, _ = _registry()
        svc, _ = self._service(self._project())
        with pytest.raises(RpcError):
            svc.start({}, _ctx(reg))

    def test_bad_threshold_rejected(self):
        reg, _ = _registry()
        svc, _ = self._service(self._project())
        with pytest.raises(RpcError):
            svc.start({"videoId": "v", "threshold": "high"}, _ctx(reg))

    def test_unknown_video(self):
        reg, _ = _registry()
        svc = diarize.Diarize(
            resolver=lambda v: None,
            load_project=lambda v: {},
            save_project=lambda v, d: None,
            models_present=lambda s: True,
        )
        with pytest.raises(RpcError):
            svc.start({"videoId": "v"}, _ctx(reg))

    def test_no_transcript_refuses(self):
        reg, _ = _registry()
        svc, _ = self._service({})  # no transcript key
        with pytest.raises(RpcError) as exc:
            svc.start({"videoId": "v"}, _ctx(reg))
        assert "transcript" in str(exc.value)

    def test_happy_path_labels_and_persists(self):
        reg, _ = _registry()
        svc, saved = self._service(self._project())
        out = svc.start({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        job = reg.get(out["jobId"])
        assert job.status.value == "done"
        assert job.result["transcript"]["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
        # persisted onto the project
        assert saved["v"]["transcript"]["segments"][0]["speaker"] == "SPEAKER_00"

    def test_offline_with_missing_models_refuses(self):
        reg, _ = _registry()
        svc, _ = self._service(self._project(), models_present=False, settings={"offline": True})
        with pytest.raises(diarize._offline.OfflineError) as exc:
            svc.start({"videoId": "v"}, _ctx(reg))
        assert "SpeechBrain" in str(exc.value)

    def test_offline_with_models_present_runs(self):
        # Offline is fine when the gated models are already installed.
        reg, _ = _registry()
        svc, _ = self._service(self._project(), models_present=True, settings={"offline": True})
        out = svc.start({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        assert reg.get(out["jobId"]).status.value == "done"

    def test_missing_job_registry_raises(self):
        # ctx.jobs is None -> INTERNAL_ERROR before any work starts.
        svc, _ = self._service(self._project())
        ctx = RpcContext(emit_notification=lambda *_: None, jobs=None)
        with pytest.raises(RpcError, match="no job registry"):
            svc.start({"videoId": "v"}, ctx)

    def test_settings_provider_raising_yields_empty(self):
        # _settings swallows a bad provider -> {} -> the job still runs to done.
        saved: dict[str, Any] = {}

        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        svc = diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=lambda v: dict(self._project()),
            save_project=lambda v, d: saved.__setitem__(v, d),
            settings_provider=boom,
            backend_factory=lambda s: FakeBackend([{"start": 0.0, "end": 2.0}], [[1.0, 0.0]]),
            models_present=lambda s: True,
        )
        reg, _ = _registry()
        out = svc.start({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        assert reg.get(out["jobId"]).status.value == "done"

    def test_cancel_after_embed_skips_persist(self):
        # Cancellation set BETWEEN raise_if_cancelled() and the persist check (via
        # the progress sink firing on "clustering speakers") -> the labelled
        # transcript is returned but NOT saved (the `if not cancelled` false branch).
        saved: dict[str, Any] = {}
        reg_holder: dict[str, Any] = {}

        def emit_progress(j, p, m):
            # Fire cancellation exactly at the post-embed "clustering speakers"
            # checkpoint (after raise_if_cancelled, before the persist check).
            if "clustering" in m:
                reg_holder["reg"].cancel(j)

        reg = JobRegistry(emit_progress=emit_progress, emit_done=lambda j, r: None)
        reg_holder["reg"] = reg
        svc = diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=lambda v: dict(self._project()),
            save_project=lambda v, d: saved.__setitem__(v, d),
            settings_provider=lambda: {},
            backend_factory=lambda s: FakeBackend(
                [{"start": 0.0, "end": 2.0}, {"start": 4.5, "end": 6.0}],
                [[1.0, 0.0], [0.0, 1.0]],
            ),
            models_present=lambda s: True,
        )
        out = svc.start({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        # Cancelled mid-flight: nothing persisted (the `if not cancelled` skips save).
        assert "v" not in saved


# --------------------------------------------------------------------------- #
# assets + register
# --------------------------------------------------------------------------- #
def test_assets_registered_in_manifest():
    from media_studio.assets import manifest

    diarize.register_diarize_assets()  # idempotent
    names = {a.name for a in manifest.all_assets()}
    assert diarize.VAD_ASSET_NAME in names
    assert diarize.ECAPA_ASSET_NAME in names


def test_register_installs_diarize_start():
    registered: dict[str, Any] = {}
    diarize.register(
        resolver=lambda v: None,
        load_project=lambda v: {},
        save_project=lambda v, d: None,
        register_fn=lambda n, f: registered.__setitem__(n, f),
    )
    assert "diarize.start" in registered


# --------------------------------------------------------------------------- #
# default heavy seams (no model / no speechbrain import touched)
# --------------------------------------------------------------------------- #
def test_default_models_present_false_when_assets_missing():
    # With no installed snapshot, default_models_present reports False (the
    # `installed_path is None` branch) — drives the offline refusal. Uses an
    # empty config dir so no real cache is consulted.
    assert diarize.default_models_present({}) is False


def test_default_models_present_true_when_all_installed(monkeypatch):
    # When BOTH gated assets report an installed path, the loop runs to the end
    # (the 335->333 continue branch) and returns True (line 337). Patch the
    # AssetManager's installed-path probe so no real HF cache is needed.
    from media_studio.assets import manager as _manager

    monkeypatch.setattr(_manager.AssetManager, "installed_path", lambda self, entry: "/cache/" + entry.name)
    # Both diarize assets are registered in the manifest at import time.
    diarize.register_diarize_assets()
    assert diarize.default_models_present({}) is True


def test_default_backend_factory_builds_speechbrain_diarizer():
    # The lazy factory imports diarize_backend and returns a SpeechBrainDiarizer
    # WITHOUT touching speechbrain/torch (those imports live inside its methods).
    from media_studio.features.diarize_backend import SpeechBrainDiarizer

    backend = diarize._default_backend_factory({"device": "cpu"})
    assert isinstance(backend, SpeechBrainDiarizer)


def test_data_root_is_a_string_path():
    # The kept-for-symmetry helper returns the config dir as a string.
    root = diarize._data_root()
    assert isinstance(root, str) and root


# --------------------------------------------------------------------------- #
# diarize_backend: module-level surface (heavy method bodies stay pragma'd)
# --------------------------------------------------------------------------- #
def test_diarize_backend_module_imports_light():
    # Importing the module is safe in the unit env: the speechbrain/torch imports
    # live INSIDE the methods, so the module-level constants/exports load without
    # the native stack. The method bodies are excluded (# pragma: no cover).
    from media_studio.features import diarize_backend as db

    assert db.TARGET_SR == 16000
    assert "SpeechBrainDiarizer" in db.__all__
    # Construction is cheap (no models loaded until detect_and_embed).
    inst = db.SpeechBrainDiarizer({"device": "cpu"})
    assert inst is not None
