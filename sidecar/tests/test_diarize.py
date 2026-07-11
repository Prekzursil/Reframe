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

    def test_concurrent_transcript_change_fails_loud_not_clobber(self):
        # A re-transcribe that lands between the RPC-time snapshot and the job's
        # save must NOT be silently overwritten by the stale, speaker-stamped
        # transcript: the job fails loud and save_project is never called.
        original = {
            "language": "en",
            "durationSec": 6.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hi"},
                {"start": 5.0, "end": 6.0, "text": "bye"},
            ],
        }
        newer = {
            "language": "ro",
            "durationSec": 6.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "salut"},
                {"start": 5.0, "end": 6.0, "text": "pa"},
            ],
        }
        # First load = RPC-time snapshot (original); second load = job-time fresh
        # reload, now carrying the concurrently re-written transcript (newer).
        loads = iter([{"transcript": original}, {"transcript": newer}])
        saved: dict[str, Any] = {}
        svc = diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=lambda v: next(loads),
            save_project=lambda v, d: saved.__setitem__(v, d),
            settings_provider=lambda: {},
            backend_factory=lambda s: FakeBackend(
                [{"start": 0.0, "end": 2.0}, {"start": 4.5, "end": 6.0}],
                [[1.0, 0.0], [0.0, 1.0]],
            ),
            models_present=lambda s: True,
        )
        reg, _ = _registry()
        out = svc.start({"videoId": "v"}, _ctx(reg))
        reg.get(out["jobId"]).wait(10)
        job = reg.get(out["jobId"])
        assert job.status.value == "error"
        assert "changed while diarization was running" in job.error
        assert "v" not in saved  # the newer transcript is preserved, not clobbered


# --------------------------------------------------------------------------- #
# pure: rename_speakers (GAP #3)
# --------------------------------------------------------------------------- #
def _diarized_transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 6.0,
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "hi", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 6.0, "text": "bye", "speaker": "SPEAKER_01"},
        ],
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
    }


class TestRenameSpeakers:
    def test_renames_segments_and_roster(self):
        t = _diarized_transcript()
        out = diarize.rename_speakers(t, {"SPEAKER_00": "Alex"})
        assert out["segments"][0]["speaker"] == "Alex"
        assert out["segments"][1]["speaker"] == "SPEAKER_01"  # unmapped passes through
        assert out["speakers"] == ["Alex", "SPEAKER_01"]
        assert out["language"] == "en"  # untouched fields preserved

    def test_does_not_mutate_input(self):
        import copy

        t = _diarized_transcript()
        before = copy.deepcopy(t)
        diarize.rename_speakers(t, {"SPEAKER_00": "Alex", "SPEAKER_01": "Sam"})
        assert t == before  # byte-identical: input never mutated

    def test_empty_mapping_is_identity(self):
        t = _diarized_transcript()
        out = diarize.rename_speakers(t, {})
        assert out["segments"] == t["segments"]
        assert out["speakers"] == t["speakers"]

    def test_mapping_label_not_in_transcript_is_noop(self):
        t = _diarized_transcript()
        out = diarize.rename_speakers(t, {"SPEAKER_99": "Ghost"})
        assert out["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
        assert out["segments"][0]["speaker"] == "SPEAKER_00"

    def test_segment_without_speaker_key_untouched(self):
        t = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "x"}],
            "speakers": [],
        }
        out = diarize.rename_speakers(t, {"SPEAKER_00": "Alex"})
        assert "speaker" not in out["segments"][0]

    def test_missing_segments_and_speakers_keys(self):
        out = diarize.rename_speakers({"language": "ro"}, {"SPEAKER_00": "Alex"})
        assert out["segments"] == []
        assert out["speakers"] == []
        assert out["language"] == "ro"


# --------------------------------------------------------------------------- #
# Diarize.rename — the direct RPC handler
# --------------------------------------------------------------------------- #
class TestRenameHandler:
    def _service(self, project, *, saved=None):
        saved = saved if saved is not None else {}

        def save(video_id, data):
            saved[video_id] = data

        svc = diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=lambda v: dict(project),
            save_project=save,
            models_present=lambda s: True,
        )
        return svc, saved

    def test_requires_video_id(self):
        reg, _ = _registry()
        svc, _ = self._service({"transcript": _diarized_transcript()})
        with pytest.raises(RpcError):
            svc.rename({"mapping": {}}, _ctx(reg))

    def test_requires_mapping_dict(self):
        reg, _ = _registry()
        svc, _ = self._service({"transcript": _diarized_transcript()})
        with pytest.raises(RpcError):
            svc.rename({"videoId": "v", "mapping": "nope"}, _ctx(reg))

    def test_no_transcript_refuses(self):
        reg, _ = _registry()
        svc, _ = self._service({})  # no transcript key
        with pytest.raises(RpcError) as exc:
            svc.rename({"videoId": "v", "mapping": {"SPEAKER_00": "Alex"}}, _ctx(reg))
        assert "transcript" in str(exc.value)

    def test_renames_persists_and_returns(self):
        reg, _ = _registry()
        svc, saved = self._service({"transcript": _diarized_transcript()})
        out = svc.rename({"videoId": "v", "mapping": {"SPEAKER_00": "Alex"}}, _ctx(reg))
        assert out["transcript"]["speakers"] == ["Alex", "SPEAKER_01"]
        assert out["transcript"]["segments"][0]["speaker"] == "Alex"
        # persisted exactly once onto a fresh project copy
        assert saved["v"]["transcript"]["segments"][0]["speaker"] == "Alex"

    def test_persists_onto_fresh_project_load(self):
        # rename re-loads the project so unrelated fields are not clobbered.
        reg, _ = _registry()
        loads: list[str] = []

        def load(video_id):
            loads.append(video_id)
            return {"transcript": _diarized_transcript(), "other": 1}

        saved: dict[str, Any] = {}
        svc = diarize.Diarize(
            resolver=lambda v: "/audio.wav",
            load_project=load,
            save_project=lambda v, d: saved.__setitem__(v, d),
            models_present=lambda s: True,
        )
        svc.rename({"videoId": "v", "mapping": {"SPEAKER_01": "Sam"}}, _ctx(reg))
        assert saved["v"]["other"] == 1  # unrelated field preserved
        assert saved["v"]["transcript"]["speakers"] == ["SPEAKER_00", "Sam"]


def test_register_installs_diarize_rename():
    registered: dict[str, Any] = {}
    diarize.register(
        resolver=lambda v: None,
        load_project=lambda v: {},
        save_project=lambda v, d: None,
        register_fn=lambda n, f: registered.__setitem__(n, f),
    )
    assert "diarize.rename" in registered


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
    assert "DiarizeBackendUnavailableError" in db.__all__
    # Construction is cheap (no models loaded until detect_and_embed).
    inst = db.SpeechBrainDiarizer({"device": "cpu"})
    assert inst is not None


# --------------------------------------------------------------------------- #
# diarize_backend: FAIL LOUD (typed) when speechbrain is unavailable
# (v1.2.0 NO-SILENT-FALLBACK — a raw ModuleNotFoundError must NOT escape).
# --------------------------------------------------------------------------- #
def test_import_speechbrain_raises_typed_error_when_missing(monkeypatch):
    # The speechbrain-ABSENT path: a sentinel ``None`` in sys.modules for the two
    # leaf modules makes the guarded import raise ImportError, which the guard
    # converts into a TYPED, actionable DiarizeBackendUnavailableError — never a
    # raw ModuleNotFoundError. Poisoning sys.modules exercises the except branch
    # DETERMINISTICALLY regardless of whether real speechbrain is installed here.
    import sys

    from media_studio.features import diarize_backend as db

    monkeypatch.setitem(sys.modules, "speechbrain.inference.classifiers", None)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", None)
    with pytest.raises(db.DiarizeBackendUnavailableError) as excinfo:
        db._import_speechbrain()
    # Actionable message NAMES speechbrain and the fix; chained from the ImportError.
    msg = str(excinfo.value).lower()
    assert "speechbrain" in msg
    assert "install" in msg or "provision" in msg
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_import_speechbrain_returns_api_when_present(monkeypatch):
    # The speechbrain-PRESENT path: inject fake ``speechbrain.inference`` modules so
    # the success branch is covered with no native stack. The guard must return the
    # (VAD, EncoderClassifier) classes it imported, in that order.
    import sys
    import types as _types

    from media_studio.features import diarize_backend as db

    class _FakeVAD: ...

    class _FakeEncoder: ...

    sb = _types.ModuleType("speechbrain")
    inference = _types.ModuleType("speechbrain.inference")
    vad_mod = _types.ModuleType("speechbrain.inference.VAD")
    cls_mod = _types.ModuleType("speechbrain.inference.classifiers")
    vad_mod.VAD = _FakeVAD
    cls_mod.EncoderClassifier = _FakeEncoder
    sb.inference = inference
    inference.VAD = vad_mod
    inference.classifiers = cls_mod
    monkeypatch.setitem(sys.modules, "speechbrain", sb)
    monkeypatch.setitem(sys.modules, "speechbrain.inference", inference)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", vad_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.classifiers", cls_mod)

    vad_cls, encoder_cls = db._import_speechbrain()
    assert vad_cls is _FakeVAD
    assert encoder_cls is _FakeEncoder


def test_ensure_models_fails_loud_when_speechbrain_missing(monkeypatch):
    # The multi-speaker diarize path enters through SpeechBrainDiarizer._ensure_models
    # (SpeechBrainDiarizer.detect_and_embed -> _ensure_models); with speechbrain
    # unavailable it must surface the SAME typed error, not a raw ModuleNotFoundError.
    import sys

    from media_studio.features import diarize_backend as db

    monkeypatch.setitem(sys.modules, "speechbrain.inference.classifiers", None)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.VAD", None)
    inst = db.SpeechBrainDiarizer({"device": "cpu"})
    with pytest.raises(db.DiarizeBackendUnavailableError):
        inst._ensure_models()


def test_fetch_safe_audio_path_forward_slashes_windows_paths():
    # SpeechBrain's VAD.get_speech_segments routes the path through split_path/fetch,
    # which mangles a Windows backslash absolute path (prepends CWD). Forward-slashing
    # is the fix; it is a no-op on already-POSIX paths.
    from media_studio.features import diarize_backend as db

    assert db._fetch_safe_audio_path(r"C:\dir\sub\a.wav") == "C:/dir/sub/a.wav"
    assert db._fetch_safe_audio_path("/tmp/x.wav") == "/tmp/x.wav"
    assert db._fetch_safe_audio_path("relative/name.wav") == "relative/name.wav"
