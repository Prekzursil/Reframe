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


def test_add_index_file_is_versioned_json(lib: Library, fake_video: Path):
    lib.add(str(fake_video))
    data = json.loads(lib.index_path.read_text(encoding="utf-8"))
    assert data["version"] == library.MANIFEST_VERSION
    assert isinstance(data["videos"], list)


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


def test_set_has_transcript(lib: Library, fake_video: Path):
    v = lib.add(str(fake_video))
    updated = lib.set_has_transcript(v["id"], True)
    assert updated["hasTranscript"] is True
    assert lib.get(v["id"])["hasTranscript"] is True


def test_set_has_transcript_unknown_id_returns_none(lib: Library):
    assert lib.set_has_transcript("nope") is None


def test_normalize_backfills_legacy_entries(tmp_path: Path):
    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({"version": 1, "videos": [{"path": "/x.mp4"}]}), encoding="utf-8")
    lib = Library(idx)
    v = lib.list()[0]
    assert v["id"]  # generated
    assert v["addedAt"]  # generated
    assert v["durationSec"] == 0.0
    assert v["hasTranscript"] is False


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
