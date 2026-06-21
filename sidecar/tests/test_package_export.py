"""Tests for features/package_export.py (captions-export: ZIP package-for-upload).

Pure-logic + a tmp-dir zip write — no model call, no network. Asserts the tag
slugging, the deterministic suggestion derivation, the override-wins behaviour,
the manifest shape, and the produced ZIP's contents.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from media_studio.features import package_export as pkg


# --------------------------------------------------------------------------- #
# slugify_tags
# --------------------------------------------------------------------------- #
def test_slugify_tags_basic() -> None:
    tags = pkg.slugify_tags("You will NOT believe this crazy trick")
    assert "believe" in tags and "crazy" in tags and "trick" in tags
    # Stop-words + short tokens dropped.
    assert "you" not in tags and "not" in tags  # "not" len 3 kept, "you" stop-word


def test_slugify_tags_dedupe_and_limit() -> None:
    tags = pkg.slugify_tags("alpha alpha beta beta gamma", max_tags=2)
    assert tags == ["alpha", "beta"]


def test_slugify_tags_empty() -> None:
    assert pkg.slugify_tags("") == []
    assert pkg.slugify_tags("a an the of") == []  # all stop-words / too short


# --------------------------------------------------------------------------- #
# build_suggestion
# --------------------------------------------------------------------------- #
def test_build_suggestion_from_hook() -> None:
    meta = {"hook": "Amazing fitness transformation", "sourceTitle": "Gym Vlog"}
    sug = pkg.build_suggestion(meta)
    assert sug["title"] == "Amazing fitness transformation"
    assert "Gym Vlog" in sug["description"]
    assert "amazing" in sug["tags"] and "fitness" in sug["tags"]


def test_build_suggestion_defaults_when_empty() -> None:
    sug = pkg.build_suggestion({})
    assert sug["title"] == pkg.DEFAULT_TITLE
    assert sug["description"] == pkg.DEFAULT_DESCRIPTION
    assert sug["tags"] == []


def test_build_suggestion_override_wins_per_field() -> None:
    meta = {"hook": "Original hook", "sourceTitle": "Vid"}
    sug = pkg.build_suggestion(meta, override={"title": "Better Title"})
    assert sug["title"] == "Better Title"
    # Description + tags still derived from meta (override only supplied a title).
    assert "Original hook" in sug["description"]
    assert "original" in sug["tags"]


def test_build_suggestion_override_tags_string() -> None:
    sug = pkg.build_suggestion({"hook": "x"}, override={"tags": "#Fitness, #Gym workout"})
    assert sug["tags"] == ["fitness", "gym", "workout"]


def test_build_suggestion_title_truncated() -> None:
    long_hook = "word " * 50
    sug = pkg.build_suggestion({"hook": long_hook})
    assert len(sug["title"]) <= pkg.MAX_TITLE_LEN


def test_build_suggestion_title_truncates_mid_word_when_no_good_boundary() -> None:
    # A single long unbroken token (no late space) hits the no-word-trim branch:
    # _truncate falls through to the hard cut at the limit.
    long_hook = "x" * 200
    sug = pkg.build_suggestion({"hook": long_hook})
    assert sug["title"] == "x" * pkg.MAX_TITLE_LEN


def test_build_suggestion_override_description_wins() -> None:
    sug = pkg.build_suggestion(
        {"hook": "Original hook", "sourceTitle": "Vid"},
        override={"description": "A hand-written description."},
    )
    assert sug["description"] == "A hand-written description."


def test_build_suggestion_override_tags_list() -> None:
    # A list/tuple override goes through the list branch of _normalize_tag_list.
    sug = pkg.build_suggestion({"hook": "x"}, override={"tags": ["#Fitness", "Gym", "Fitness"]})
    assert sug["tags"] == ["fitness", "gym"]  # dedup + lower + leading-# stripped


def test_build_suggestion_override_tags_non_list_string_is_empty() -> None:
    # A non-(str/list/tuple) tags override -> the else branch returns []. The int
    # is truthy so the override-tags branch is taken (slugify is NOT used).
    sug = pkg.build_suggestion({"hook": "real hook words"}, override={"tags": 12345})
    assert sug["tags"] == []


def test_normalize_tag_list_skips_empty_tokens() -> None:
    # An empty/whitespace-only token is skipped (the falsy-token continue branch).
    sug = pkg.build_suggestion({"hook": "x"}, override={"tags": ["valid", "", "  ", "#"]})
    assert sug["tags"] == ["valid"]


def test_normalize_tag_list_caps_at_max_tags() -> None:
    many = [f"tag{i}" for i in range(pkg.MAX_TAGS + 5)]
    sug = pkg.build_suggestion({"hook": "x"}, override={"tags": many})
    assert len(sug["tags"]) == pkg.MAX_TAGS


# --------------------------------------------------------------------------- #
# build_manifest
# --------------------------------------------------------------------------- #
def test_build_manifest_shape() -> None:
    meta = {
        "videoId": "v1",
        "sourceTitle": "My Video",
        "template": "karaoke",
        "viralityPct": 88,
        "durationSec": 14.5,
        "hook": "Hook here",
    }
    sug = pkg.build_suggestion(meta)
    manifest = pkg.build_manifest(meta, sug)
    assert manifest["title"] == sug["title"]
    assert manifest["tags"] == sug["tags"]
    src = manifest["source"]
    assert src["videoId"] == "v1"
    assert src["template"] == "karaoke"
    assert src["viralityPct"] == 88
    assert src["durationSec"] == 14.5


def test_build_manifest_virality_non_int_becomes_none() -> None:
    manifest = pkg.build_manifest({"viralityPct": "high"}, {"title": "t", "description": "d", "tags": []})
    assert manifest["source"]["viralityPct"] is None


# --------------------------------------------------------------------------- #
# package (file I/O)
# --------------------------------------------------------------------------- #
def make_clip(tmp_path: Path, *, with_thumb: bool = True) -> Path:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00fake-mp4")
    if with_thumb:
        (tmp_path / "clip.thumb.jpg").write_bytes(b"\xff\xd8jpg")
    return clip


def test_package_writes_zip_with_all_parts(tmp_path: Path) -> None:
    clip = make_clip(tmp_path)
    out = tmp_path / "bundle.zip"
    meta = {"hook": "Great clip", "sourceTitle": "Source", "viralityPct": 70}
    res = pkg.package(clip, out, meta=meta, thumbnail_path=tmp_path / "clip.thumb.jpg")
    assert Path(res["path"]) == out
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert names == {pkg.ARC_VIDEO, pkg.ARC_THUMBNAIL, pkg.ARC_MANIFEST}
        manifest = json.loads(zf.read(pkg.ARC_MANIFEST))
    assert manifest["title"] == "Great clip"
    assert res["manifest"] == manifest


def test_package_without_thumbnail(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, with_thumb=False)
    out = tmp_path / "bundle.zip"
    pkg.package(clip, out, meta={"hook": "h"})
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert pkg.ARC_THUMBNAIL not in names
    assert pkg.ARC_VIDEO in names and pkg.ARC_MANIFEST in names


def test_package_thumbnail_missing_file_skipped(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, with_thumb=False)
    out = tmp_path / "bundle.zip"
    # Pointing at a non-existent thumb is tolerated (skipped, not raised).
    pkg.package(clip, out, meta={}, thumbnail_path=tmp_path / "nope.jpg")
    with zipfile.ZipFile(out) as zf:
        assert pkg.ARC_THUMBNAIL not in zf.namelist()


def test_package_missing_clip_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pkg.package(tmp_path / "nope.mp4", tmp_path / "out.zip")


def test_package_suggestion_override(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, with_thumb=False)
    out = tmp_path / "b.zip"
    res = pkg.package(clip, out, meta={"hook": "h"}, suggestion={"title": "Custom"})
    assert res["manifest"]["title"] == "Custom"


def test_package_creates_parent_dirs(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, with_thumb=False)
    out = tmp_path / "nested" / "deep" / "b.zip"
    pkg.package(clip, out, meta={})
    assert out.exists()
