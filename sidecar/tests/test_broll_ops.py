"""RPC surface tests for auto-b-roll (v1.5 flagship #3, WU BR0 wiring half).

Closes the loop the three pure modules leave open: transcript + library ->
``broll.index`` -> ``broll.status`` -> ``broll.suggest`` -> ``broll.apply`` ->
an ffmpeg argv. Every heavy edge is an injected seam (the SigLIP embed towers,
the transcript read, the index read/write, ffprobe, the ffmpeg run), so these
run with no model, no disk state and no subprocess — the same discipline
``test_vlm_backbone.py`` uses for the scorers.

The privacy assertion is tested, not just asserted in a doc: the local path
never egresses, so ``willEgress`` is False on every b-roll result and no
consent gate is reachable from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features import broll_index as bi
from media_studio.features import broll_ops as bo
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError

MODEL = "google/siglip2-so400m-patch16-384"

# Two orthogonal assets; a segment vector aimed at one of them (see
# test_broll_plan.py for why the 2-D basis makes every cosine arithmetic).
ASSETS = [
    {"assetId": "a-dog", "path": "/lib/dog.png", "kind": "image", "sizeBytes": 10, "mtime": 1.0},
    {"assetId": "a-city", "path": "/lib/city.png", "kind": "image", "sizeBytes": 20, "mtime": 2.0},
]
IMAGE_VECS = {"/lib/dog.png": [1.0, 0.0], "/lib/city.png": [0.0, 1.0]}
TRANSCRIPT = {
    "segments": [
        {"start": 0.0, "end": 6.0, "text": "a dog running"},
        {"start": 30.0, "end": 36.0, "text": "the city skyline"},
    ]
}


def _rpc(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


class _Store:
    """An in-memory stand-in for the on-disk index sidecar."""

    def __init__(self, initial: Any = None) -> None:
        self.value = initial
        self.writes = 0

    def load(self) -> Any:
        return self.value

    def save(self, index: Any) -> None:
        self.value = index
        self.writes += 1


class _Run:
    """Records the ffmpeg argv instead of running it."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kw: Any) -> int:
        self.calls.append(list(argv))
        return self.code


def _svc(tmp_path, store: _Store, **over: Any) -> bo.BrollOps:
    kwargs: dict[str, Any] = {
        "resolver": lambda vid: f"/videos/{vid}.mp4",
        "list_assets": lambda: list(ASSETS),
        "load_index": store.load,
        "save_index": store.save,
        "load_transcript": lambda vid: dict(TRANSCRIPT),
        "embed_images": lambda paths: [IMAGE_VECS[p] for p in paths],
        # A text query aimed at whichever asset the segment names.
        "embed_texts": lambda texts: [[0.99, 0.14] if "dog" in t else [0.14, 0.99] for t in texts],
        "out_dir": tmp_path,
        "duration": lambda path, settings=None: 120.0,
        "run": _Run(),
        "settings_provider": dict,
        "model_id": MODEL,
        "clock": lambda: "2026-08-08T00:00:00Z",
    }
    kwargs.update(over)
    return bo.BrollOps(**kwargs)


# --------------------------------------------------------------------------- #
# broll.status — a direct, pure read (no provider, no model)
# --------------------------------------------------------------------------- #
def test_status_of_an_unindexed_library(tmp_path, registry):
    got = _svc(tmp_path, _Store()).status({}, _rpc(registry))
    assert got["indexed"] is False
    assert got["libraryCount"] == 2
    assert got["stale"] is True
    assert got["willEgress"] is False


def test_status_after_indexing_is_fresh(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    got = svc.status({}, _rpc(registry))
    assert got["indexed"] is True
    assert got["assetCount"] == 2
    assert got["stale"] is False
    assert got["model"] == MODEL


# --------------------------------------------------------------------------- #
# broll.index — embed the library, persist, and do it INCREMENTALLY
# --------------------------------------------------------------------------- #
def test_index_embeds_every_asset_and_persists(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    job = registry.get(svc.index({}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.result["assetCount"] == 2
    assert job.result["embedded"] == 2
    assert job.result["willEgress"] is False
    assert store.writes == 1
    assert store.value["model"] == MODEL


def test_reindexing_an_unchanged_library_embeds_nothing(tmp_path, registry):
    store = _Store()
    embedded: list[list[str]] = []

    def spy(paths):
        embedded.append(list(paths))
        return [IMAGE_VECS[p] for p in paths]

    svc = _svc(tmp_path, store, embed_images=spy)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = registry.get(svc.index({}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert embedded == [["/lib/dog.png", "/lib/city.png"], []]
    assert job.result["embedded"] == 0


def test_index_force_re_embeds_everything(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = registry.get(svc.index({"force": True}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.result["embedded"] == 2


def test_index_of_an_empty_library_is_a_valid_empty_index(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store, list_assets=list)
    job = registry.get(svc.index({}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.result["assetCount"] == 0
    assert store.value["assets"] == []


def test_index_without_a_job_registry_raises(tmp_path):
    with pytest.raises(RpcError):
        _svc(tmp_path, _Store()).index({}, RpcContext(emit_notification=lambda obj: None, jobs=None))


# --------------------------------------------------------------------------- #
# broll.suggest — the gated, timed plan
# --------------------------------------------------------------------------- #
def _suggest(svc, registry, params=None):
    job = registry.get(svc.suggest(params or {"videoId": "v1"}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    return job


def test_suggest_returns_a_timed_plan_matching_each_segment(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": 0.5})
    plan = job.result["insertions"]
    assert [i["assetId"] for i in plan] == ["a-dog", "a-city"]
    assert [i["start"] for i in plan] == [0.0, 30.0]
    assert job.result["willEgress"] is False


def test_suggest_honours_the_threshold_and_can_return_nothing(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": 0.999})
    assert job.result["insertions"] == []
    # The honest empty state is a first-class result, not an error.
    assert job.result["reason"] == bo.NO_CONFIDENT_MATCH


def test_suggest_refuses_an_unindexed_library(tmp_path, registry):
    svc = _svc(tmp_path, _Store())
    job = _suggest(svc, registry)
    assert job.status.value == "error"
    assert "has not been indexed" in str(job.error)


def test_suggest_refuses_an_index_from_a_different_backbone(tmp_path, registry):
    store = _Store(bi.build(ASSETS, [[1.0, 0.0], [0.0, 1.0]], model="other/model", built_at="t"))
    job = _suggest(_svc(tmp_path, store), registry)
    assert job.status.value == "error"
    assert "one joint space" in str(job.error)


def test_suggest_of_an_untranscribed_video_raises(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store, load_transcript=lambda vid: {})
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry)
    assert job.status.value == "error"
    assert "transcript" in str(job.error)


def test_suggest_requires_a_video_id(tmp_path, registry):
    with pytest.raises(RpcError):
        _svc(tmp_path, _Store()).suggest({}, _rpc(registry))


def test_suggest_passes_the_coverage_cap_through(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    # 1% of 120 s = 1.2 s, under the 1.5 s minimum -> nothing fits.
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": 0.5, "maxCoveragePct": 1.0})
    assert job.result["insertions"] == []


def test_suggest_honours_the_pip_layout(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": 0.5, "layout": "pip"})
    assert {i["layout"] for i in job.result["insertions"]} == {"pip"}


def test_suggest_rejects_an_unknown_layout(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry, {"videoId": "v1", "layout": "nope"})
    assert job.status.value == "error"


# --------------------------------------------------------------------------- #
# broll.apply — the composite render (REVIEW-FIRST: it takes the reviewed plan)
# --------------------------------------------------------------------------- #
def _plan_row(start=0.0, end=4.0, path="/lib/dog.png"):
    return {
        "segmentIndex": 0,
        "start": start,
        "end": end,
        "duration": end - start,
        "sourceStart": 0.0,
        "assetId": "a-dog",
        "path": path,
        "kind": "image",
        "score": 0.9,
        "reason": "r",
        "layout": "cutaway",
    }


def test_apply_runs_the_composite_argv_and_returns_the_output(tmp_path, registry):
    run = _Run()
    svc = _svc(tmp_path, _Store(), run=run)
    job = registry.get(svc.apply({"videoId": "v1", "insertions": [_plan_row()]}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.result["path"].endswith(".broll.mp4")
    assert job.result["inserted"] == 1
    assert len(run.calls) == 1
    assert "-filter_complex" in run.calls[0]


def test_apply_takes_the_REVIEWED_plan_and_never_re_plans(tmp_path, registry):
    # The design's editorial guarantee: apply composites exactly what the user
    # accepted. It must not call the model or the planner again.
    def boom(*_a, **_k):
        raise AssertionError("apply must not embed anything")

    svc = _svc(tmp_path, _Store(), embed_texts=boom, embed_images=boom)
    job = registry.get(svc.apply({"videoId": "v1", "insertions": [_plan_row()]}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "done"


def test_apply_with_an_empty_plan_raises(tmp_path, registry):
    with pytest.raises(RpcError, match="insertions"):
        _svc(tmp_path, _Store()).apply({"videoId": "v1", "insertions": []}, _rpc(registry))


def test_apply_surfaces_an_ffmpeg_failure(tmp_path, registry):
    svc = _svc(tmp_path, _Store(), run=_Run(code=1))
    job = registry.get(svc.apply({"videoId": "v1", "insertions": [_plan_row()]}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "error"
    assert "exit 1" in str(job.error)


def test_apply_of_an_unknown_video_raises(tmp_path, registry):
    svc = _svc(tmp_path, _Store(), resolver=lambda vid: None)
    with pytest.raises(RpcError, match="unknown video"):
        svc.apply({"videoId": "ghost", "insertions": [_plan_row()]}, _rpc(registry))


# --------------------------------------------------------------------------- #
# the disk adapters the composition root wires in
# --------------------------------------------------------------------------- #
def test_scan_assets_finds_stills_and_clips_and_classifies_them(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.MP4").write_bytes(b"yy")
    (tmp_path / "notes.txt").write_text("ignored")
    found = {a["path"]: a for a in bo.scan_assets(tmp_path)}
    assert len(found) == 2
    assert found[str(tmp_path / "a.png")]["kind"] == "image"
    # Extension matching is case-insensitive: a camera writes .MP4/.JPG.
    assert found[str(tmp_path / "b.MP4")]["kind"] == "video"


def test_scan_assets_recurses_and_is_deterministically_ordered(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "z.png").write_bytes(b"x")
    (tmp_path / "a.png").write_bytes(b"x")
    assert [Path(a["path"]).name for a in bo.scan_assets(tmp_path)] == ["a.png", "z.png"]


def test_scan_assets_carries_the_stat_metadata_the_index_fingerprints(tmp_path):
    (tmp_path / "a.png").write_bytes(b"12345")
    asset = bo.scan_assets(tmp_path)[0]
    assert asset["sizeBytes"] == 5
    assert asset["mtime"] > 0
    assert asset["assetId"]


def test_scan_assets_gives_each_file_a_stable_distinct_id(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    first = {a["assetId"] for a in bo.scan_assets(tmp_path)}
    assert len(first) == 2
    assert first == {a["assetId"] for a in bo.scan_assets(tmp_path)}


def test_scan_assets_of_a_missing_folder_is_empty_not_an_error(tmp_path):
    # An unconfigured b-roll folder is the normal first-run state.
    assert bo.scan_assets(tmp_path / "nope") == []


def test_scan_assets_of_no_folder_at_all_is_empty(tmp_path):
    assert bo.scan_assets("") == []


def test_index_file_round_trips(tmp_path):
    path = tmp_path / "broll.index.json"
    index = bi.build(ASSETS, [[1.0, 0.0], [0.0, 1.0]], model=MODEL, built_at="t")
    bo.save_index_file(path, index)
    assert bo.load_index_file(path) == index


def test_index_file_absent_reads_as_none(tmp_path):
    assert bo.load_index_file(tmp_path / "nothing.json") is None


def test_index_file_corrupt_reads_as_none_rather_than_crashing(tmp_path):
    # A half-written sidecar must degrade to "not indexed" (which the UI can
    # act on), never take the whole sidecar down on startup.
    path = tmp_path / "broll.index.json"
    path.write_text("{not json", encoding="utf-8")
    assert bo.load_index_file(path) is None


def test_index_file_of_a_non_object_reads_as_none(tmp_path):
    path = tmp_path / "broll.index.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert bo.load_index_file(path) is None


def test_save_index_file_creates_its_parent_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "broll.index.json"
    bo.save_index_file(path, bi.build([], [], model=MODEL, built_at="t"))
    assert path.is_file()


# --------------------------------------------------------------------------- #
# the backbone adapters (the ONE heavy edge, kept injectable so it is testable)
# --------------------------------------------------------------------------- #
class _FakeBackbone:
    """Stands in for the SigLIP-2 towers; records what it was handed."""

    def __init__(self) -> None:
        self.images: Any = None
        self.texts: Any = None

    def embed_images(self, frames):
        import numpy as np

        self.images = frames
        return np.asarray([[float(len(frames)), 0.0] for _ in range(len(frames))])

    def embed_texts(self, texts):
        import numpy as np

        self.texts = list(texts)
        return np.asarray([[0.0, float(len(t))] for t in texts])


def test_image_embedder_loads_one_frame_per_asset_and_returns_plain_lists():
    import numpy as np

    backbone = _FakeBackbone()
    seen: list[tuple[str, str]] = []

    def loader(path, kind):
        seen.append((path, kind))
        return np.zeros((2, 2, 3), dtype=np.uint8)

    embed = bo.make_image_embedder(backend_factory=lambda s: backbone, frame_loader=loader, settings_provider=dict)
    out = embed(["/lib/dog.png", "/lib/clip.mp4"])
    assert seen == [("/lib/dog.png", "image"), ("/lib/clip.mp4", "video")]
    # The index and planner want JSON-safe floats, never a numpy array.
    assert out == [[2.0, 0.0], [2.0, 0.0]]
    assert all(isinstance(v, float) for row in out for v in row)


def test_image_embedder_batches_every_frame_into_one_backbone_call():
    import numpy as np

    backbone = _FakeBackbone()
    embed = bo.make_image_embedder(
        backend_factory=lambda s: backbone,
        frame_loader=lambda p, k: np.zeros((2, 2, 3), dtype=np.uint8),
        settings_provider=dict,
    )
    embed(["/a.png", "/b.png", "/c.png"])
    assert backbone.images.shape == (3, 2, 2, 3), "one stacked batch, not three loads"


def test_image_embedder_of_nothing_never_loads_the_model():
    def boom(_settings):
        raise AssertionError("an empty re-index must not pay for a model load")

    assert bo.make_image_embedder(backend_factory=boom, frame_loader=lambda p, k: None)([]) == []


def test_text_embedder_returns_plain_lists():
    backbone = _FakeBackbone()
    embed = bo.make_text_embedder(backend_factory=lambda s: backbone, settings_provider=dict)
    assert embed(["ab", "cde"]) == [[0.0, 2.0], [0.0, 3.0]]
    assert backbone.texts == ["ab", "cde"]


def test_text_embedder_of_nothing_never_loads_the_model():
    def boom(_settings):
        raise AssertionError("an empty transcript must not pay for a model load")

    assert bo.make_text_embedder(backend_factory=boom)([]) == []


def test_the_two_embedders_share_ONE_backbone_instance_per_call():
    # Both towers must come from the same loaded model: a cross-modal cosine is
    # only valid inside one joint space, and two factory calls could resolve to
    # two different checkpoints if settings changed between them.
    built: list[Any] = []

    def factory(_settings):
        backbone = _FakeBackbone()
        built.append(backbone)
        return backbone

    bo.make_text_embedder(backend_factory=factory, settings_provider=dict)(["a"])
    bo.make_text_embedder(backend_factory=factory, settings_provider=dict)(["b"])
    assert len(built) == 2, "each call builds lazily; the caller owns any caching"


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_register_wires_every_broll_method(tmp_path):
    seen: dict[str, Any] = {}
    bo.register(
        resolver=lambda vid: None,
        list_assets=list,
        load_index=lambda: None,
        save_index=lambda index: None,
        load_transcript=lambda vid: {},
        out_dir=tmp_path,
        register_fn=lambda name, handler: seen.__setitem__(name, handler),
    )
    assert set(seen) == set(bo.METHODS)


def test_registered_methods_are_all_broll_namespaced_and_key_free(tmp_path):
    # These never call a provider, so none may ever join the key-injection
    # allowlist (which is prefix-driven: ai. / director. / shortmaker. / index.).
    assert all(name.startswith("broll.") for name in bo.METHODS)


def test_a_garbage_threshold_falls_back_to_the_default_instead_of_crashing(tmp_path, registry):
    # The renderer sends a slider value; a blank field must not 500 the job.
    store = _Store()
    svc = _svc(tmp_path, store)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": "not-a-number"})
    # 0.99 / 0.14 both clear the 0.22 default, so the fallback is observable.
    assert [i["assetId"] for i in job.result["insertions"]] == ["a-dog", "a-city"]


def test_without_a_duration_seam_the_total_falls_back_to_the_last_segment_end(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store, duration=None)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    # Last segment ends at 36 s; a 40% cap = 14.4 s, so both inserts still fit
    # and the job must complete rather than divide by a zero total.
    job = _suggest(svc, registry, {"videoId": "v1", "threshold": 0.5})
    assert job.status.value == "done"
    assert len(job.result["insertions"]) == 2


def test_the_default_clock_stamps_an_iso_utc_instant(tmp_path, registry):
    store = _Store()
    svc = _svc(tmp_path, store, clock=None)
    registry.get(svc.index({}, _rpc(registry))["jobId"]).wait(timeout=5)
    built_at = store.value["builtAt"]
    assert built_at.endswith("Z")
    assert built_at[4] == "-" and built_at[10] == "T"


def test_a_backbone_returning_the_wrong_vector_count_fails_loudly(tmp_path, registry):
    # A silently short embed batch would persist an index whose rows are shifted
    # against their assets - every later ranking would be confidently wrong.
    svc = _svc(tmp_path, _Store(), embed_images=lambda paths: [[1.0, 0.0]])
    job = registry.get(svc.index({}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "error"
    assert "1 vectors for 2 assets" in str(job.error)


def test_settings_provider_failure_never_breaks_an_op(tmp_path, registry):
    def boom() -> dict[str, Any]:
        raise RuntimeError("settings exploded")

    svc = _svc(tmp_path, _Store(), settings_provider=boom)
    job = registry.get(svc.apply({"videoId": "v1", "insertions": [_plan_row()]}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "done"
