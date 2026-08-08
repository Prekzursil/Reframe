"""PURE b-roll asset index tests (v1.5 flagship #3, WU BR2).

The index is the only persisted state auto-b-roll owns, and the two ways it can
be quietly wrong are the ones tested hardest here:

* **a stale row** — the file on disk changed but its vector did not, so the
  planner ranks the OLD picture;
* **a model mismatch** — a cross-modal cosine is only meaningful inside ONE
  joint space, so scoring a SigLIP text vector against a Nomic image vector
  produces a confident, meaningless number. That must be a typed refusal, never
  a silent ranking.

No model here either: vectors arrive as plain lists through the same injected
seam the planner uses.
"""

from __future__ import annotations

import pytest
from media_studio.features import broll_index as bi

MODEL = "google/siglip2-so400m-patch16-384"
OTHER_MODEL = "nomic-ai/nomic-embed-vision-v1.5"
BUILT_AT = "2026-08-08T00:00:00Z"


def _asset(asset_id: str, path: str, *, size: int = 100, mtime: float = 1.0, kind: str = "image"):
    return {"assetId": asset_id, "path": path, "kind": kind, "sizeBytes": size, "mtime": mtime}


A = _asset("a1", "/lib/dog.png")
B = _asset("a2", "/lib/city.png", size=200, mtime=2.0)
VECS = [[1.0, 0.0], [0.0, 1.0]]


# --------------------------------------------------------------------------- #
# fingerprint — the staleness key
# --------------------------------------------------------------------------- #
def test_fingerprint_is_stable_for_the_same_bytes():
    assert bi.fingerprint(A) == bi.fingerprint(dict(A))


def test_fingerprint_changes_when_the_file_is_rewritten():
    assert bi.fingerprint(A) != bi.fingerprint(_asset("a1", "/lib/dog.png", size=101))
    assert bi.fingerprint(A) != bi.fingerprint(_asset("a1", "/lib/dog.png", mtime=9.0))


def test_fingerprint_changes_when_the_asset_is_a_different_file():
    assert bi.fingerprint(A) != bi.fingerprint(_asset("a1", "/lib/other.png"))


def test_fingerprint_of_an_asset_with_no_stat_metadata_still_works():
    assert isinstance(bi.fingerprint({"assetId": "x", "path": "/p"}), str)


# --------------------------------------------------------------------------- #
# build — the persisted shape
# --------------------------------------------------------------------------- #
def test_build_produces_a_versioned_index_with_one_row_per_asset():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    assert index["version"] == bi.INDEX_VERSION
    assert index["model"] == MODEL
    assert index["dim"] == 2
    assert index["builtAt"] == BUILT_AT
    assert [row["assetId"] for row in index["assets"]] == ["a1", "a2"]
    assert index["assets"][0]["vector"] == [1.0, 0.0]
    assert index["assets"][0]["fingerprint"] == bi.fingerprint(A)


def test_build_of_an_empty_library_is_an_empty_but_valid_index():
    index = bi.build([], [], model=MODEL, built_at=BUILT_AT)
    assert index["assets"] == []
    assert index["dim"] == 0


def test_build_requires_one_vector_per_asset():
    with pytest.raises(ValueError, match="one vector per asset"):
        bi.build([A, B], VECS[:1], model=MODEL, built_at=BUILT_AT)


def test_build_rejects_ragged_vectors():
    with pytest.raises(ValueError, match="same dimension"):
        bi.build([A, B], [[1.0, 0.0], [0.0, 1.0, 0.0]], model=MODEL, built_at=BUILT_AT)


def test_build_rejects_an_empty_model_id():
    # An index that does not know which joint space it lives in cannot be
    # checked against a query later.
    with pytest.raises(ValueError, match="model"):
        bi.build([A], [VECS[0]], model="", built_at=BUILT_AT)


def test_build_is_json_round_trippable():
    import json

    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    assert json.loads(json.dumps(index)) == index


# --------------------------------------------------------------------------- #
# rows — the (assets, vectors) pair the planner consumes
# --------------------------------------------------------------------------- #
def test_rows_returns_planner_shaped_assets_and_aligned_vectors():
    assets, vectors = bi.rows(bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT))
    assert [a["assetId"] for a in assets] == ["a1", "a2"]
    assert [a["path"] for a in assets] == ["/lib/dog.png", "/lib/city.png"]
    assert vectors == VECS
    assert "vector" not in assets[0], "the planner takes vectors as its own argument"


def test_rows_of_an_empty_index():
    assert bi.rows(bi.build([], [], model=MODEL, built_at=BUILT_AT)) == ([], [])


# --------------------------------------------------------------------------- #
# require_model — the cross-space refusal
# --------------------------------------------------------------------------- #
def test_require_model_passes_on_a_matching_backbone():
    bi.require_model(bi.build([A], [VECS[0]], model=MODEL, built_at=BUILT_AT), MODEL)


def test_require_model_refuses_a_different_backbone():
    index = bi.build([A], [VECS[0]], model=MODEL, built_at=BUILT_AT)
    with pytest.raises(bi.StaleIndexError) as excinfo:
        bi.require_model(index, OTHER_MODEL)
    # The message must name BOTH models: "re-index" is only actionable when the
    # user can see which one they have and which one they asked for.
    assert MODEL in str(excinfo.value)
    assert OTHER_MODEL in str(excinfo.value)


def test_require_model_refuses_a_missing_index():
    with pytest.raises(bi.StaleIndexError, match="not been indexed"):
        bi.require_model(None, MODEL)


# --------------------------------------------------------------------------- #
# refresh_plan — incremental re-index
# --------------------------------------------------------------------------- #
def test_refresh_plan_on_no_index_embeds_everything():
    plan = bi.refresh_plan(None, [A, B], model=MODEL)
    assert plan["rebuildAll"] is True
    assert [i for i, _ in plan["embed"]] == [0, 1]


def test_refresh_plan_reuses_unchanged_assets():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    plan = bi.refresh_plan(index, [A, B], model=MODEL)
    assert plan["embed"] == []
    assert plan["rebuildAll"] is False


def test_refresh_plan_re_embeds_only_the_changed_asset():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    edited = _asset("a2", "/lib/city.png", size=999, mtime=2.0)
    plan = bi.refresh_plan(index, [A, edited], model=MODEL)
    assert [i for i, _ in plan["embed"]] == [1]


def test_refresh_plan_embeds_a_newly_added_asset():
    index = bi.build([A], [VECS[0]], model=MODEL, built_at=BUILT_AT)
    plan = bi.refresh_plan(index, [A, B], model=MODEL)
    assert [i for i, _ in plan["embed"]] == [1]


def test_refresh_plan_rebuilds_everything_on_a_model_change():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    plan = bi.refresh_plan(index, [A, B], model=OTHER_MODEL)
    assert plan["rebuildAll"] is True
    assert [i for i, _ in plan["embed"]] == [0, 1]


def test_refresh_plan_forced_rebuild_ignores_a_fresh_index():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    plan = bi.refresh_plan(index, [A, B], model=MODEL, force=True)
    assert plan["rebuildAll"] is True
    assert len(plan["embed"]) == 2


def test_refresh_plan_drops_a_removed_asset_without_re_embedding_the_rest():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    plan = bi.refresh_plan(index, [A], model=MODEL)
    assert plan["embed"] == []
    assert bi.merge(plan, [A], {}, model=MODEL, built_at=BUILT_AT)["assets"][0]["assetId"] == "a1"
    assert len(bi.merge(plan, [A], {}, model=MODEL, built_at=BUILT_AT)["assets"]) == 1


# --------------------------------------------------------------------------- #
# merge — fold the freshly-embedded vectors back in
# --------------------------------------------------------------------------- #
def test_merge_keeps_reused_vectors_and_takes_the_new_one():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    edited = _asset("a2", "/lib/city.png", size=999, mtime=2.0)
    plan = bi.refresh_plan(index, [A, edited], model=MODEL)
    merged = bi.merge(plan, [A, edited], {1: [0.5, 0.5]}, model=MODEL, built_at="later")
    assert merged["assets"][0]["vector"] == [1.0, 0.0]  # reused, not re-embedded
    assert merged["assets"][1]["vector"] == [0.5, 0.5]  # the fresh embedding
    assert merged["assets"][1]["fingerprint"] == bi.fingerprint(edited)
    assert merged["builtAt"] == "later"


def test_merge_refuses_a_missing_embedding():
    plan = bi.refresh_plan(None, [A], model=MODEL)
    with pytest.raises(ValueError, match="no embedding"):
        bi.merge(plan, [A], {}, model=MODEL, built_at=BUILT_AT)


# --------------------------------------------------------------------------- #
# status — what the UI shows
# --------------------------------------------------------------------------- #
def test_status_of_an_unindexed_library():
    assert bi.status(None, [A, B], model=MODEL) == {
        "indexed": False,
        "assetCount": 0,
        "libraryCount": 2,
        "model": "",
        "dim": 0,
        "stale": True,
        "staleCount": 2,
    }


def test_status_of_a_fresh_index():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    assert bi.status(index, [A, B], model=MODEL) == {
        "indexed": True,
        "assetCount": 2,
        "libraryCount": 2,
        "model": MODEL,
        "dim": 2,
        "stale": False,
        "staleCount": 0,
    }


def test_status_counts_the_stale_rows():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    got = bi.status(index, [A, _asset("a2", "/lib/city.png", size=999)], model=MODEL)
    assert got["stale"] is True
    assert got["staleCount"] == 1


def test_status_reports_a_model_change_as_wholly_stale():
    index = bi.build([A, B], VECS, model=MODEL, built_at=BUILT_AT)
    got = bi.status(index, [A, B], model=OTHER_MODEL)
    assert got["stale"] is True
    assert got["staleCount"] == 2


def test_status_of_an_empty_library_against_an_empty_index_is_fresh():
    index = bi.build([], [], model=MODEL, built_at=BUILT_AT)
    got = bi.status(index, [], model=MODEL)
    assert got["stale"] is False
    assert got["staleCount"] == 0
