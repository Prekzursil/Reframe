"""Tests for audio-track management (features/tracks_audio.py, T2).

DONE criteria covered: the mux argv PRESERVES existing subtitle+audio streams
(mocked ffmpeg — assert the maps, never spawn), and the project-manifest
``audioTracks`` persistence round-trips through a real on-disk JSON store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import tracks_audio as ta
from media_studio.protocol import RpcContext, RpcError

SETTINGS = {"ffmpegPath": "C:/tools/ffmpeg/ffmpeg.exe"}


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# A3 model + manifest edits (pure)
# --------------------------------------------------------------------------- #
class TestModel:
    def test_normalize_backfills_frozen_fields(self):
        track = ta.normalize_audio_track({"id": "a1", "kind": "dub", "path": "x.m4a"})
        assert set(track) == {"id", "lang", "name", "kind", "path"}
        assert track["lang"] == "und"

    def test_voice_kept_only_when_present(self):
        with_voice = ta.normalize_audio_track({"kind": "dub", "voice": "af_sarah", "path": "x"})
        assert with_voice["voice"] == "af_sarah"
        assert "voice" not in ta.normalize_audio_track({"kind": "dub", "path": "x"})

    def test_bad_kind_rejected(self):
        with pytest.raises(ta.AudioTrackError, match="kind"):
            ta.normalize_audio_track({"kind": "hard", "path": "x"})

    def test_add_find_remove_round_trip(self):
        project: dict[str, Any] = {}
        track = ta.add_audio_track(project, {"id": "a1", "kind": "dub", "path": "x"})
        assert ta.find_audio_track(project, "a1") is track
        assert ta.audio_track_index(project, "a1") == 0
        # idempotent re-add
        assert ta.add_audio_track(project, {"id": "a1", "kind": "dub"}) is track
        assert len(project["audioTracks"]) == 1
        removed = ta.remove_audio_track(project, "a1")
        assert removed["id"] == "a1"
        assert project["audioTracks"] == []

    def test_find_unknown_raises(self):
        with pytest.raises(ta.AudioTrackError, match="no such"):
            ta.find_audio_track({}, "ghost")


# --------------------------------------------------------------------------- #
# argv builders — stream preservation is the headline contract
# --------------------------------------------------------------------------- #
class TestArgvBuilders:
    def test_mux_preserves_all_streams_and_appends_audio(self):
        argv = ta.build_mux_argv(
            "C:/vids/movie with spaces.mkv",
            "C:/dubs/dub.m4a",
            "C:/vids/out.mkv",
            lang="de",
            existing_audio_count=2,
            settings=SETTINGS,
        )
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        # -map 0 keeps EVERY source stream: video + audio + SUBTITLES
        pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]
        assert ("-map", "0") in pairs
        assert ("-map", "1:a") in pairs
        assert ("-c", "copy") in pairs  # nothing re-encoded, nothing dropped
        # no negative map: nothing is excluded by a mux
        assert not any(a.startswith("-0:") for a in argv)
        assert ("-metadata:s:a:2", "language=de") in pairs
        assert argv[-1] == "C:/vids/out.mkv"
        # both inputs present (argv list keeps spaced paths intact)
        i_positions = [i for i, a in enumerate(argv) if a == "-i"]
        assert argv[i_positions[0] + 1] == "C:/vids/movie with spaces.mkv"
        assert argv[i_positions[1] + 1] == "C:/dubs/dub.m4a"

    def test_replace_swaps_exactly_one_stream(self):
        argv = ta.build_replace_argv("in.mkv", "new.m4a", "out.mkv", stream_index=1, lang="en", settings=SETTINGS)
        pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]
        assert ("-map", "0") in pairs
        assert ("-map", "-0:a:1") in pairs  # ONLY the replaced stream is dropped
        assert ("-map", "1:a") in pairs
        assert ("-c", "copy") in pairs

    def test_strip_drops_exactly_one_stream_no_second_input(self):
        argv = ta.build_strip_audio_argv("in.mkv", "out.mkv", stream_index=0, settings=SETTINGS)
        pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]
        assert ("-map", "0") in pairs
        assert ("-map", "-0:a:0") in pairs
        assert argv.count("-i") == 1
        assert ("-c", "copy") in pairs

    def test_negative_indices_rejected(self):
        with pytest.raises(ta.AudioTrackError):
            ta.build_replace_argv("i", "a", "o", stream_index=-1, settings=SETTINGS)
        with pytest.raises(ta.AudioTrackError):
            ta.build_strip_audio_argv("i", "o", stream_index=-1, settings=SETTINGS)


class TestOriginalsFromProbe:
    def test_audio_streams_seeded_in_container_order(self):
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "tags": {"language": "eng", "title": "Stereo"}},
                {"codec_type": "subtitle", "codec_name": "subrip"},
                {"codec_type": "audio"},
            ]
        }
        rows = ta.original_tracks_from_probe(probe, "C:/v.mkv")
        assert len(rows) == 2
        assert rows[0]["lang"] == "eng" and rows[0]["name"] == "Stereo"
        assert rows[1]["lang"] == "und" and rows[1]["name"] == "Audio 2"
        assert all(r["kind"] == "original" and r["path"] == "C:/v.mkv" for r in rows)

    def test_garbage_probe_seeds_nothing(self):
        assert ta.original_tracks_from_probe({}, "v") == []
        assert ta.original_tracks_from_probe({"streams": "nope"}, "v") == []


# --------------------------------------------------------------------------- #
# the service — manifest persistence round-trip (REAL on-disk JSON store)
# --------------------------------------------------------------------------- #
PROBE_ONE_AUDIO = {
    "streams": [
        {"codec_type": "video", "codec_name": "h264"},
        {"codec_type": "audio", "tags": {"language": "eng"}},
    ]
}


class DiskStore:
    """A minimal per-video JSON project store (what the wiring agent binds)."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, video_id: str) -> Path:
        return self.root / f"{video_id}.json"

    def load(self, video_id: str) -> dict[str, Any]:
        p = self._path(video_id)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"id": video_id, "video": {"id": video_id}, "tracks": [], "clips": []}

    def save(self, video_id: str, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(video_id).write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_service(tmp_path, *, run=None, probe=None, store=None):
    video = tmp_path / "video.mkv"
    video.write_bytes(b"fake container")
    disk = store or DiskStore(tmp_path / "projects")
    service = ta.AudioTracksService(
        resolver=lambda vid: str(video) if vid == "v1" else None,
        load_project=disk.load,
        save_project=disk.save,
        settings_provider=lambda: SETTINGS,
        run=run or (lambda argv, **kw: 0),
        duration=lambda path, settings=None: 60.0,
        probe=probe or (lambda path, settings=None: PROBE_ONE_AUDIO),
    )
    return service, disk, video


class TestService:
    def test_list_seeds_originals_and_persists(self, tmp_path):
        service, disk, _video = make_service(tmp_path)
        result = service.list({"videoId": "v1"}, ctx())
        assert len(result["audioTracks"]) == 1
        original = result["audioTracks"][0]
        assert original["kind"] == "original" and original["lang"] == "eng"
        # persisted: a FRESH service over the same store sees the same row
        service2, _, _ = make_service(tmp_path, store=disk)
        again = service2.list({"videoId": "v1"}, ctx())
        assert again["audioTracks"] == result["audioTracks"]

    def test_list_unknown_video_rejected(self, tmp_path):
        service, _, _ = make_service(tmp_path)
        with pytest.raises(RpcError, match="unknown video"):
            service.list({"videoId": "ghost"}, ctx())

    def test_mux_runs_ffmpeg_and_round_trips_manifest(self, tmp_path):
        argvs = []

        def run(argv, **kwargs):
            argvs.append(list(argv))
            return 0

        service, disk, video = make_service(tmp_path, run=run)
        dub = tmp_path / "dub.m4a"
        dub.write_bytes(b"aac")
        result = service.mux(
            {"videoId": "v1", "path": str(dub), "lang": "de", "name": "German dub", "kind": "dub"},
            ctx(),
        )
        track = result["audioTrack"]
        assert track["kind"] == "dub" and track["lang"] == "de"
        assert track["path"] == str(dub)
        # the ffmpeg call mapped everything + the new audio (stream-preserving)
        pairs = [(a, b) for a, b in zip(argvs[0], argvs[0][1:], strict=False)]
        assert ("-map", "0") in pairs and ("-map", "1:a") in pairs
        # the new stream's metadata index = the 1 seeded original
        assert ("-metadata:s:a:1", "language=de") in pairs
        # manifest ROUND-TRIP: a fresh service lists original + dub, in order
        service2, _, _ = make_service(tmp_path, store=disk)
        rows = service2.list({"videoId": "v1"}, ctx())["audioTracks"]
        assert [r["kind"] for r in rows] == ["original", "dub"]
        assert rows[1]["id"] == track["id"]

    def test_mux_missing_audio_file_rejected(self, tmp_path):
        service, _, _ = make_service(tmp_path)
        with pytest.raises(RpcError, match="not found"):
            service.mux(
                {"videoId": "v1", "path": str(tmp_path / "ghost.m4a"), "lang": "de", "name": "x", "kind": "dub"},
                ctx(),
            )

    def test_mux_ffmpeg_failure_surfaces_and_does_not_persist(self, tmp_path):
        service, disk, _ = make_service(tmp_path, run=lambda argv, **kw: 1)
        dub = tmp_path / "dub.m4a"
        dub.write_bytes(b"aac")
        with pytest.raises(RpcError, match="mux failed"):
            service.mux(
                {"videoId": "v1", "path": str(dub), "lang": "de", "name": "x", "kind": "dub"},
                ctx(),
            )
        rows = disk.load("v1").get("audioTracks") or []
        assert all(r.get("kind") != "dub" for r in rows)

    def test_replace_updates_path_and_uses_stream_index(self, tmp_path):
        argvs = []
        service, disk, _ = make_service(tmp_path, run=lambda argv, **kw: argvs.append(list(argv)) or 0)
        dub1 = tmp_path / "a.m4a"
        dub1.write_bytes(b"a")
        service.mux(
            {"videoId": "v1", "path": str(dub1), "lang": "de", "name": "d", "kind": "dub"},
            ctx(),
        )
        track_id = disk.load("v1")["audioTracks"][1]["id"]
        dub2 = tmp_path / "b.m4a"
        dub2.write_bytes(b"b")
        result = service.replace({"videoId": "v1", "audioTrackId": track_id, "path": str(dub2)}, ctx())
        assert result["audioTrack"]["path"] == str(dub2)
        # the replace argv negatively mapped a:1 (the dub's container index)
        pairs = [(a, b) for a, b in zip(argvs[-1], argvs[-1][1:], strict=False)]
        assert ("-map", "-0:a:1") in pairs and ("-map", "1:a") in pairs
        assert disk.load("v1")["audioTracks"][1]["path"] == str(dub2)

    def test_strip_removes_row_and_returns_path(self, tmp_path):
        argvs = []
        service, disk, _ = make_service(tmp_path, run=lambda argv, **kw: argvs.append(list(argv)) or 0)
        service.list({"videoId": "v1"}, ctx())  # seed the original
        track_id = disk.load("v1")["audioTracks"][0]["id"]
        result = service.strip({"videoId": "v1", "audioTrackId": track_id}, ctx())
        assert result["path"]
        pairs = [(a, b) for a, b in zip(argvs[-1], argvs[-1][1:], strict=False)]
        assert ("-map", "-0:a:0") in pairs
        assert disk.load("v1")["audioTracks"] == []

    def test_replace_unknown_track_rejected(self, tmp_path):
        service, _, _ = make_service(tmp_path)
        dub = tmp_path / "x.m4a"
        dub.write_bytes(b"x")
        with pytest.raises(RpcError, match="no such audio track"):
            service.replace({"videoId": "v1", "audioTrackId": "ghost", "path": str(dub)}, ctx())

    def test_mux_for_dub_records_voice(self, tmp_path):
        service, disk, _ = make_service(tmp_path)
        dub = tmp_path / "dub.m4a"
        dub.write_bytes(b"aac")
        track = service.mux_for_dub("v1", str(dub), lang="de", name="German dub", voice="af_sarah")
        assert track["voice"] == "af_sarah"
        rows = disk.load("v1")["audioTracks"]
        assert rows[-1]["voice"] == "af_sarah"


# --------------------------------------------------------------------------- #
# register() — frozen A2 names
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_registers_exactly_the_a2_names(self, tmp_path):
        registered = {}
        store = DiskStore(tmp_path / "projects")
        service = ta.register(
            resolver=lambda vid: None,
            load_project=store.load,
            save_project=store.save,
            register_fn=lambda name, h: registered.__setitem__(name, h),
        )
        assert set(registered) == {
            "tracks.audio.list",
            "tracks.audio.mux",
            "tracks.audio.replace",
            "tracks.audio.strip",
        }
        assert isinstance(service, ta.AudioTracksService)
