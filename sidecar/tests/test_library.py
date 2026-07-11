"""Unit tests for media_studio.library (Library + Project).

No heavy-ML / ffmpeg imports: the duration prober is injected as a plain stub,
so these tests run with stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from media_studio import library
from media_studio.library import Library, Project


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_video(tmp_path: Path) -> Path:
    p = tmp_path / "my talk.mp4"  # space in name on purpose
    p.write_bytes(b"\x00\x00fakebytes")
    return p


@pytest.fixture
def lib(tmp_path: Path) -> Library:
    # prober returns a fixed duration so no subprocess is ever touched
    return Library(tmp_path / "index.json", probe_duration=lambda _p: 123.5)


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #
def test_list_empty_when_no_index(lib: Library):
    assert lib.list() == []


def test_add_returns_full_video_schema(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    assert set(v.keys()) == {
        "id",
        "path",
        "title",
        "addedAt",
        "durationSec",
        "hasTranscript",
        "thumbnailPath",  # WU-2: additive Video field (default "")
    }
    assert v["durationSec"] == 123.5
    assert v["hasTranscript"] is False
    assert v["title"] == "my talk"  # stem default
    assert Path(v["path"]).name == "my talk.mp4"
    assert v["id"]


def test_add_persists_to_index_and_list_reads_it(lib: Library, fake_video: Path):
    lib.add(str(fake_video))
    again = Library(lib.index_path, probe_duration=lambda _p: 0.0)
    listed = again.list()
    assert len(listed) == 1
    assert listed[0]["title"] == "my talk"


def test_add_persists_to_sqlite_db_not_json_index(lib: Library, fake_video: Path):
    # L1 storage contract: the live store is a SQLite DB derived from index_path
    # (`*.json` -> `*.db`), NOT a JSON index file. add() never writes the JSON.
    lib.add(str(fake_video))
    db = lib.index_path.with_suffix(".db")
    assert db.exists()
    assert not lib.index_path.exists()


def test_add_custom_title(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video), title="Custom")
    assert v["title"] == "Custom"


def test_add_missing_file_raises(lib: Library, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        lib.add(str(tmp_path / "nope.mp4"))


def test_add_is_idempotent_on_same_path(lib: Library, fake_video: Path):
    a = lib.add(str(fake_video))
    b = lib.add(str(fake_video))
    assert a["id"] == b["id"]
    assert len(lib.list()) == 1


def test_add_stores_resolved_absolute_path(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    assert Path(v["path"]).is_absolute()


def test_add_probe_failure_defaults_duration_to_zero(tmp_path: Path, fake_video: Path):
    def boom(_p):
        raise RuntimeError("ffprobe exploded")

    lib = Library(tmp_path / "idx.json", probe_duration=boom)
    v = lib.add(str(fake_video))
    assert v["durationSec"] == 0.0


def test_get_returns_video_or_none(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    assert lib.get(v["id"])["id"] == v["id"]
    assert lib.get("does-not-exist") is None


def test_remove_existing_returns_true(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    assert lib.remove(v["id"]) is True
    assert lib.list() == []


def test_remove_missing_returns_false(lib: Library):
    assert lib.remove("ghost") is False


def test_remove_does_not_delete_source_file(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    lib.remove(v["id"])
    assert fake_video.exists()  # file on disk is untouched


def test_remove_evicts_managed_copy(lib: Library, fake_video: Path):
    # A removed video's opt-in managed byte-copy must be reclaimed, not orphaned:
    # otherwise its row + content-addressed file count forever against the cap with
    # no entity left to evict them. Covers the has_managed=True branch of remove().
    from media_studio.keepcopy import ManagedStore

    v = lib.add(str(fake_video))
    managed = ManagedStore(lib).keep_copy(v["id"])  # real copier + blake3 + disk_usage
    managed_file = Path(managed["managedPath"])
    assert managed_file.exists()
    assert lib.managed_status()["count"] == 1

    assert lib.remove(v["id"]) is True
    assert lib.get(v["id"]) is None
    assert lib.managed_status()["count"] == 0  # row reclaimed
    assert not managed_file.exists()  # bytes freed


def test_set_has_transcript(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    updated = lib.set_has_transcript(v["id"], True)
    assert updated["hasTranscript"] is True
    assert lib.get(v["id"])["hasTranscript"] is True


def test_set_has_transcript_unknown_id_returns_none(lib: Library):
    assert lib.set_has_transcript("nope") is None


def test_add_second_distinct_path_skips_non_matching_existing(lib: Library, tmp_path: Path):
    # With one video already in the index, adding a DIFFERENT path walks past the
    # non-matching existing row (137 -> 136 loop continue) and appends a new one.
    first = tmp_path / "first.mp4"
    first.write_bytes(b"a")
    second = tmp_path / "second.mp4"
    second.write_bytes(b"b")
    v1 = lib.add(str(first))
    v2 = lib.add(str(second))
    assert v1["id"] != v2["id"]
    assert {v["title"] for v in lib.list()} == {"first", "second"}


def test_set_has_transcript_skips_non_matching_rows(lib: Library, tmp_path: Path):
    # Two videos: marking one must skip the other in the loop (184 -> 183).
    a = tmp_path / "a.mp4"
    a.write_bytes(b"a")
    b = tmp_path / "b.mp4"
    b.write_bytes(b"b")
    va = lib.add(str(a))
    vb = lib.add(str(b))
    updated = lib.set_has_transcript(vb["id"], True)
    assert updated["id"] == vb["id"]
    assert lib.get(va["id"])["hasTranscript"] is False
    assert lib.get(vb["id"])["hasTranscript"] is True


def test_normalize_backfills_legacy_entries(tmp_path: Path):
    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({"version": 1, "videos": [{"path": "/x.mp4"}]}), encoding="utf-8")
    lib = Library(idx)
    v = lib.list()[0]
    assert v["id"]  # generated
    assert v["addedAt"]  # generated
    assert v["durationSec"] == 0.0
    assert v["hasTranscript"] is False


# --------------------------------------------------------------------------- #
# WU-2: thumbnailPath (additive Video field) + set_thumbnail setter
# --------------------------------------------------------------------------- #
def test_add_includes_thumbnail_path_default_empty(lib: Library, fake_video: Path):
    # A freshly added Video carries the additive thumbnailPath, defaulting to "".
    v = lib.add(str(fake_video))
    assert v["thumbnailPath"] == ""


def test_normalize_backfills_missing_thumbnail_path(tmp_path: Path):
    # A legacy Video record with NO thumbnailPath loads as "" (no KeyError).
    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({"version": 1, "videos": [{"path": "/x.mp4"}]}), encoding="utf-8")
    lib = Library(idx)
    assert lib.list()[0]["thumbnailPath"] == ""


def test_normalize_preserves_existing_thumbnail_path(tmp_path: Path):
    # A stored thumbnailPath survives the normalize round-trip.
    idx = tmp_path / "idx.json"
    idx.write_text(
        json.dumps({"version": 1, "videos": [{"path": "/x.mp4", "thumbnailPath": "/p/t.jpg"}]}),
        encoding="utf-8",
    )
    lib = Library(idx)
    assert lib.list()[0]["thumbnailPath"] == "/p/t.jpg"


def test_set_thumbnail_persists_and_returns_video(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    updated = lib.set_thumbnail(v["id"], "/posters/x.jpg")
    assert updated is not None
    assert updated["thumbnailPath"] == "/posters/x.jpg"
    # Persisted: a fresh re-read of the index shows the poster path.
    again = Library(lib.index_path, probe_duration=lambda _p: 0.0)
    assert again.get(v["id"])["thumbnailPath"] == "/posters/x.jpg"


def test_set_thumbnail_unknown_id_returns_none(lib: Library):
    assert lib.set_thumbnail("nope", "/p/t.jpg") is None


def test_set_thumbnail_skips_non_matching_rows(lib: Library, tmp_path: Path):
    # Two videos: setting one must skip the other in the loop.
    a = tmp_path / "a.mp4"
    a.write_bytes(b"a")
    b = tmp_path / "b.mp4"
    b.write_bytes(b"b")
    va = lib.add(str(a))
    vb = lib.add(str(b))
    updated = lib.set_thumbnail(vb["id"], "/p/b.jpg")
    assert updated["id"] == vb["id"]
    assert lib.get(va["id"])["thumbnailPath"] == ""
    assert lib.get(vb["id"])["thumbnailPath"] == "/p/b.jpg"


def test_default_probe_uses_ffmpeg_lazy(monkeypatch, tmp_path: Path, fake_video: Path):
    # _default_probe should import ffmpeg lazily and call ffprobe_duration
    calls = {}

    def fake_ffprobe_duration(path):
        calls["path"] = path
        return 7.0

    import media_studio.ffmpeg as ff

    monkeypatch.setattr(ff, "ffprobe_duration", fake_ffprobe_duration)

    lib = Library(tmp_path / "idx.json")  # no prober -> default
    v = lib.add(str(fake_video))
    assert v["durationSec"] == 7.0
    assert calls["path"] == v["path"]


# --------------------------------------------------------------------------- #
# Project
# --------------------------------------------------------------------------- #
def _video(path: str, vid: str = "vid1") -> dict:
    return {
        "id": vid,
        "path": path,
        "title": "t",
        "addedAt": "2026-01-01T00:00:00Z",
        "durationSec": 10.0,
        "hasTranscript": False,
    }


def test_project_new_has_schema(fake_video: Path):
    p = Project.new(_video(str(fake_video)), settings={"useCloud": False})
    assert set(p.data.keys()) >= {"id", "video", "tracks", "clips", "settings"}
    assert p.data["tracks"] == []
    assert p.data["clips"] == []
    assert p.data["settings"]["useCloud"] is False
    assert "transcript" not in p.data  # optional


def test_project_save_and_open_round_trip(tmp_path: Path, fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    manifest = tmp_path / "proj" / "project.json"
    p.save(manifest)
    assert manifest.exists()
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    assert raw["version"] == library.MANIFEST_VERSION

    reopened = Project.open(manifest)
    assert reopened.data["id"] == p.data["id"]
    assert reopened.data["video"]["path"] == str(fake_video)


def test_project_save_without_path_raises(fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    with pytest.raises(ValueError):
        p.save()


def test_project_open_preserves_optional_transcript(tmp_path: Path):
    manifest = tmp_path / "p.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "p1",
                "video": {"path": "/v.mp4"},
                "transcript": {"language": "en", "segments": [], "durationSec": 1.0},
                "tracks": [],
                "clips": [],
                "settings": {},
            }
        ),
        encoding="utf-8",
    )
    p = Project.open(manifest)
    assert p.data["transcript"]["language"] == "en"


def test_project_open_invalid_manifest_raises(tmp_path: Path):
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError):
        Project.open(manifest)


def test_find_missing_sources_detects_absent_video(tmp_path: Path):
    p = Project.new(_video(str(tmp_path / "gone.mp4")))
    assert p.find_missing_sources() == [str(tmp_path / "gone.mp4")]


def test_find_missing_sources_empty_when_present(fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    assert p.find_missing_sources() == []


def test_find_missing_sources_checks_clips_and_tracks(tmp_path: Path, fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    p.data["clips"] = [{"candidate": {"rank": 1}, "path": str(tmp_path / "clip-gone.mp4")}]
    p.data["tracks"] = [{"id": "t1", "path": str(tmp_path / "subs-gone.srt")}]
    missing = p.find_missing_sources()
    assert str(tmp_path / "clip-gone.mp4") in missing
    assert str(tmp_path / "subs-gone.srt") in missing


def test_find_missing_sources_resolves_relative_against_manifest(tmp_path: Path):
    # relative ref present next to manifest -> not missing
    folder = tmp_path / "proj"
    (folder / "assets").mkdir(parents=True)
    (folder / "assets" / "v.mp4").write_bytes(b"x")
    manifest = folder / "project.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "p",
                "video": {"path": "assets/v.mp4"},
                "tracks": [],
                "clips": [],
                "settings": {},
            }
        ),
        encoding="utf-8",
    )
    p = Project.open(manifest)
    assert p.find_missing_sources() == []


# --------------------------------------------------------------------------- #
# consolidate
# --------------------------------------------------------------------------- #
def test_consolidate_copies_video_and_rebases_ref(tmp_path: Path, fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    out = tmp_path / "consolidated"
    folder = p.consolidate(out)

    assert Path(folder) == out.resolve()
    # the video ref is now relative + the bytes copied in
    assert p.data["video"]["path"] == "assets/my talk.mp4"
    assert (out / "assets" / "my talk.mp4").exists()
    # manifest written into the folder
    assert (out / "project.json").exists()


def test_consolidate_produces_self_contained_project(tmp_path: Path, fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    out = tmp_path / "bundle"
    p.consolidate(out)
    # re-open the consolidated manifest and confirm nothing is missing
    reopened = Project.open(out / "project.json")
    assert reopened.find_missing_sources() == []


def test_consolidate_copies_clips_and_tracks(tmp_path: Path, fake_video: Path):
    clip = tmp_path / "clip1.mp4"
    clip.write_bytes(b"clip")
    track = tmp_path / "subs.srt"
    track.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    p = Project.new(_video(str(fake_video)))
    p.data["clips"] = [{"candidate": {"rank": 1}, "path": str(clip)}]
    p.data["tracks"] = [{"id": "t1", "path": str(track)}]

    out = tmp_path / "c"
    p.consolidate(out)
    assert p.data["clips"][0]["path"] == "assets/clip1.mp4"
    assert p.data["tracks"][0]["path"] == "assets/subs.srt"
    assert (out / "assets" / "clip1.mp4").exists()
    assert (out / "assets" / "subs.srt").exists()


def test_consolidate_skips_missing_source(tmp_path: Path, fake_video: Path):
    p = Project.new(_video(str(fake_video)))
    p.data["clips"] = [{"candidate": {}, "path": str(tmp_path / "missing.mp4")}]
    out = tmp_path / "c"
    p.consolidate(out)
    # video copied, missing clip ref left untouched
    assert p.data["video"]["path"] == "assets/my talk.mp4"
    assert p.data["clips"][0]["path"] == str(tmp_path / "missing.mp4")


def test_consolidate_disambiguates_same_basename(tmp_path: Path):
    a = tmp_path / "a" / "clip.mp4"
    b = tmp_path / "b" / "clip.mp4"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    p = Project.new(_video(str(a)))
    p.data["clips"] = [{"candidate": {}, "path": str(b)}]
    out = tmp_path / "c"
    p.consolidate(out)
    names = sorted(x.name for x in (out / "assets").iterdir())
    assert names == ["clip-1.mp4", "clip.mp4"]


def test_consolidate_dedups_identical_ref(tmp_path: Path, fake_video: Path):
    # Two refs to the SAME absolute file (video + a clip) must be copied ONCE and
    # both rebased to the SAME assets/<name> (memo-hit branch of _copy_in), instead
    # of duplicating the bytes under diverging "name" / "name-1" copies.
    p = Project.new(_video(str(fake_video)))
    p.data["clips"] = [{"candidate": {}, "path": str(fake_video)}]
    out = tmp_path / "c"
    p.consolidate(out)
    names = [x.name for x in (out / "assets").iterdir()]
    assert names == ["my talk.mp4"]  # exactly one copy
    assert p.data["video"]["path"] == "assets/my talk.mp4"
    assert p.data["clips"][0]["path"] == "assets/my talk.mp4"  # both point at it


def test_consolidate_rebases_thumbnail_path(tmp_path: Path, fake_video: Path):
    # The source-video poster is copied + rebased relative so a moved portable
    # folder still finds it (thumbnailPath-present branch of consolidate).
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"jpeg")
    video = _video(str(fake_video))
    video["thumbnailPath"] = str(poster)
    p = Project.new(video)
    out = tmp_path / "c"
    p.consolidate(out)
    assert p.data["video"]["thumbnailPath"] == "assets/poster.jpg"
    assert (out / "assets" / "poster.jpg").exists()


def test_consolidate_leaves_missing_thumbnail_path_untouched(tmp_path: Path, fake_video: Path):
    # A poster whose file has vanished is left as-is (a regenerable derived artifact
    # is NOT a relinkable source), exercising the missing-source arm for thumbnailPath.
    video = _video(str(fake_video))
    video["thumbnailPath"] = str(tmp_path / "gone-poster.jpg")
    p = Project.new(video)
    out = tmp_path / "c"
    p.consolidate(out)
    assert p.data["video"]["thumbnailPath"] == str(tmp_path / "gone-poster.jpg")
    # and it was NOT reported as a missing SOURCE (poster stays out of _ref_paths)
    reopened = Project.open(out / "project.json")
    assert reopened.find_missing_sources() == []


def test_consolidate_disambiguates_three_same_basename(tmp_path: Path):
    # Three files share a basename: "clip.mp4" then "clip-1.mp4" are taken, so
    # _unique_name must advance i past 1 (the while-loop increment, line 333).
    paths = []
    for sub in ("a", "b", "c"):
        f = tmp_path / sub / "clip.mp4"
        f.parent.mkdir()
        f.write_bytes(sub.encode())
        paths.append(f)
    p = Project.new(_video(str(paths[0])))
    p.data["clips"] = [
        {"candidate": {}, "path": str(paths[1])},
        {"candidate": {}, "path": str(paths[2])},
    ]
    out = tmp_path / "c"
    p.consolidate(out)
    names = sorted(x.name for x in (out / "assets").iterdir())
    assert names == ["clip-1.mp4", "clip-2.mp4", "clip.mp4"]


# --------------------------------------------------------------------------- #
# _ref_paths / consolidate — entries WITHOUT a usable path (branch coverage)
# --------------------------------------------------------------------------- #
def test_ref_paths_skips_entries_without_paths(tmp_path: Path):
    # video has no path; clips/tracks include a non-dict and a dict with no path
    # -> every "has-path" branch takes its false arm (260->262, 263->262, 266->265).
    data = {
        "id": "p",
        "video": {},  # no "path"
        "clips": ["not-a-dict", {"candidate": {}}],  # non-dict + dict w/o path
        "tracks": [{"id": "t1"}],  # dict w/o path
        "settings": {},
    }
    p = Project(data)
    assert p.find_missing_sources() == []  # nothing referenced -> nothing missing


def test_consolidate_skips_entries_without_paths(tmp_path: Path):
    # Same shape through consolidate: the video/clip/track "has-path" guards all
    # take their false arm (312->314, 315->314, 318->317) so nothing is copied.
    data = {
        "id": "p",
        "video": {},  # no path
        "clips": ["bad", {"candidate": {}}],  # non-dict + dict w/o path
        "tracks": [{"id": "t1"}],  # dict w/o path
        "settings": {},
    }
    p = Project(data)
    out = tmp_path / "empty"
    p.consolidate(out)
    # assets dir exists but is empty (no refs had a copyable path)
    assert (out / "assets").is_dir()
    assert list((out / "assets").iterdir()) == []
    assert (out / "project.json").exists()
