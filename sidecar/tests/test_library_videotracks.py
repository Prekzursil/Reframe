"""``videoTracks`` must survive the manifest round-trip AND stay portable.

The audio side already learned this the hard way (library.py:597-601, 665-669:
"dub AudioTracks carry a 'path' too — include them so a deleted dub is reported
missing and consolidate can rebase it"). A video CLIP carries a ``path`` for the
same reason, so it needs the same three behaviours or a consolidated project
silently points at files that are not in the portable folder:

  1. ``Project.open`` backfills ``videoTracks`` (an older manifest has none);
  2. ``find_missing_sources`` reports a deleted clip source;
  3. ``consolidate`` copies each clip source in and REBASES its ref.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from media_studio import library


def _video(path: Path) -> dict[str, Any]:
    return {"id": "v1", "path": str(path), "durationSec": 10.0}


def _manifest(tmp_path: Path, video: Path, clip_src: Path) -> Path:
    payload = {
        "version": 1,
        "id": "p1",
        "video": _video(video),
        "tracks": [],
        "clips": [],
        "audioTracks": [],
        "videoTracks": [
            {
                "id": "vt1",
                "name": "Video 1",
                "index": 0,
                "clips": [
                    {"id": "c1", "path": str(video), "srcIn": 0.0, "srcOut": 2.0, "timelineStart": 0.0},
                    {"id": "c2", "path": str(clip_src), "srcIn": 1.0, "srcOut": 2.0, "timelineStart": 2.0},
                ],
            }
        ],
        "settings": {},
    }
    manifest = tmp_path / "project.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


class TestPersistence:
    def test_open_backfills_videoTracks_on_an_older_manifest(self, tmp_path: Path):
        manifest = tmp_path / "old.json"
        manifest.write_text(json.dumps({"id": "p1", "video": {}}), encoding="utf-8")
        project = library.Project.open(manifest)
        assert project.data["videoTracks"] == []

    def test_videoTracks_round_trip_through_save_and_open(self, tmp_path: Path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"v")
        broll = tmp_path / "b.mp4"
        broll.write_bytes(b"b")
        reopened = library.Project.open(_manifest(tmp_path, video, broll))
        reopened.save()
        again = library.Project.open(tmp_path / "project.json")
        assert [c["id"] for c in again.data["videoTracks"][0]["clips"]] == ["c1", "c2"]
        assert again.data["videoTracks"][0]["clips"][1]["srcOut"] == 2.0


class TestPortability:
    def test_a_deleted_clip_source_is_reported_missing(self, tmp_path: Path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"v")
        broll = tmp_path / "gone.mp4"  # deliberately never created
        project = library.Project.open(_manifest(tmp_path, video, broll))
        assert str(broll) in project.find_missing_sources()

    def test_consolidate_copies_and_rebases_every_clip_source(self, tmp_path: Path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"v")
        broll = tmp_path / "b.mp4"
        broll.write_bytes(b"b")
        project = library.Project.open(_manifest(tmp_path, video, broll))
        dest = tmp_path / "portable"
        project.consolidate(dest)
        clips = project.data["videoTracks"][0]["clips"]
        assert [c["path"] for c in clips] == ["assets/a.mp4", "assets/b.mp4"]
        assert (dest / "assets" / "b.mp4").is_file()
        # the video ref and the clip ref to the SAME file dedup onto one copy
        assert project.data["video"]["path"] == "assets/a.mp4"
        assert sorted(p.name for p in (dest / "assets").iterdir()) == ["a.mp4", "b.mp4"]


class TestMalformedRowsAreSkippedNotFatal:
    """A hand-edited / older manifest must not crash the ref walk or consolidate.

    Both video-lane loops mirror the audio-track loops' defensive shape, so both
    directions are exercised here: a lane that is not an object at all, and a clip
    row with no usable ``path``.
    """

    def _project(self, tmp_path: Path) -> library.Project:
        video = tmp_path / "a.mp4"
        video.write_bytes(b"v")
        payload = {
            "id": "p1",
            "video": _video(video),
            "videoTracks": [
                "not-a-lane",
                {"id": "vt1", "clips": ["not-a-clip", {"id": "c1"}, {"id": "c2", "path": ""}]},
                {"id": "vt2"},  # no clips key at all
            ],
        }
        manifest = tmp_path / "project.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return library.Project.open(manifest)

    def test_ref_walk_skips_them(self, tmp_path: Path):
        project = self._project(tmp_path)
        assert project.find_missing_sources() == []

    def test_consolidate_skips_them(self, tmp_path: Path):
        project = self._project(tmp_path)
        project.consolidate(tmp_path / "portable")
        assert project.data["videoTracks"][0] == "not-a-lane"
        assert project.data["videoTracks"][1]["clips"][1] == {"id": "c1"}
