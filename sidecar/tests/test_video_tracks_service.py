"""The ``tracks.video.*`` service + every model guard (features/video_tracks.py).

``test_video_tracks.py`` owns the TIMING contract; this file owns the wire
surface, the manifest persistence round-trip (a REAL on-disk JSON store) and
every fail-closed guard, so an edit can never be silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import video_tracks as vt
from media_studio.features.nle_export import seconds_to_frames
from media_studio.protocol import RpcContext, RpcError

SETTINGS = {"ffmpegPath": "C:/tools/ffmpeg/ffmpeg.exe"}


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def job_ctx(registry: Any) -> RpcContext:
    """An RpcContext WITH a job registry (tracks.video.render defers to a job)."""
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def a_clip(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "c1",
        "path": "C:/vids/a.mp4",
        "srcIn": 0.0,
        "srcOut": 2.0,
        "timelineStart": 0.0,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# fps resolution — a wrong frame rate mis-snaps every edit, so it never guesses
# --------------------------------------------------------------------------- #
class TestResolveFps:
    def test_explicit_value_wins(self):
        assert vt.resolve_fps(60, {"exportDefaults": {"nleFps": 24}}) == 60

    def test_explicit_bad_value_raises_instead_of_defaulting(self):
        with pytest.raises(vt.VideoTrackError, match="unsupported fps"):
            vt.resolve_fps(29.97)

    def test_settings_supply_the_timeline_rate(self):
        assert vt.resolve_fps(None, {"exportDefaults": {"nleFps": 25}}) == 25

    def test_bad_settings_value_warns_and_falls_back(self, monkeypatch):
        warnings: list[tuple] = []
        monkeypatch.setattr(vt.log, "warning", lambda *a, **k: warnings.append(a))
        assert vt.resolve_fps(None, {"exportDefaults": {"nleFps": 999}}) == vt.DEFAULT_FPS
        assert warnings and "nleFps" in warnings[0][0]

    def test_no_settings_at_all_uses_the_default(self):
        assert vt.resolve_fps(None, None) == vt.DEFAULT_FPS
        assert vt.resolve_fps(None, {"exportDefaults": "not-a-dict"}) == vt.DEFAULT_FPS
        assert vt.resolve_fps(None, {"exportDefaults": {}}) == vt.DEFAULT_FPS

    def test_snap_quantizes_and_clamps(self):
        assert vt.snap(1.017, 30) == pytest.approx(31 / 30)
        assert vt.snap(-5.0, 30) == 0.0

    def test_half_frame_ties_are_pinned_for_the_renderer_mirror(self):
        """The exact tie values the client mirror must reproduce.

        ``app/renderer/src/lib/videoTimelineOps.ts`` re-implements this quantizer
        so a drag preview can be clamped locally. Python's ``round`` is
        half-to-EVEN while JS ``Math.round`` is half-UP, so on a tie the two
        disagree by ONE FRAME and the preview jumps when the sidecar commits its
        own value. Measured: ``2.5 / 30 * 30 == 2.5`` exactly in both runtimes, so
        the tie is reachable, not theoretical. These two assertions and the
        matching pair in ``videoTimelineOps.test.ts`` pin BOTH sides to the same
        numbers — change one and the other goes red.
        """
        assert seconds_to_frames(2.5 / 30, 30) == 2  # NOT 3 (half-up would give 3)
        assert seconds_to_frames(3.5 / 30, 30) == 4


# --------------------------------------------------------------------------- #
# model guards
# --------------------------------------------------------------------------- #
class TestModelGuards:
    def test_clip_must_be_an_object_with_a_path(self):
        with pytest.raises(vt.VideoTrackError, match="must be an object"):
            vt.normalize_video_clip("nope", fps=30)  # type: ignore[arg-type]
        with pytest.raises(vt.VideoTrackError, match="source path"):
            vt.normalize_video_clip({"srcIn": 0.0, "srcOut": 1.0}, fps=30)

    def test_sub_frame_clip_is_refused(self):
        with pytest.raises(vt.VideoTrackError, match="at least 1 frame"):
            vt.normalize_video_clip(a_clip(srcIn=0.0, srcOut=0.0), fps=30)

    def test_track_must_be_an_object_with_a_clip_list(self):
        with pytest.raises(vt.VideoTrackError, match="must be an object"):
            vt.normalize_video_track([], fps=30)  # type: ignore[arg-type]
        with pytest.raises(vt.VideoTrackError, match="clips must be a list"):
            vt.normalize_video_track({"clips": "x"}, fps=30)

    @pytest.mark.parametrize("index", [True, -1, "0", 1.5])
    def test_lane_index_must_be_a_non_negative_int(self, index: Any):
        with pytest.raises(vt.VideoTrackError, match="index must be"):
            vt.normalize_video_track({"index": index}, fps=30)

    def test_lane_name_defaults_from_its_index(self):
        assert vt.normalize_video_track({"index": 2}, fps=30)["name"] == "Video 3"
        assert vt.normalize_video_track({"index": 0, "name": "B-roll"}, fps=30)["name"] == "B-roll"

    def test_videoTracks_must_be_a_list(self):
        with pytest.raises(vt.VideoTrackError, match="videoTracks must be a list"):
            vt.video_tracks_of({"videoTracks": {}})

    def test_clips_must_be_a_list(self):
        with pytest.raises(vt.VideoTrackError, match="clips must be a list"):
            vt.clips_of({"clips": 3})

    def test_find_skips_malformed_rows_and_raises_when_absent(self):
        project: dict[str, Any] = {
            "videoTracks": [
                "junk",
                {"id": "vt1", "clips": ["junk", vt.normalize_video_clip(a_clip(), fps=30)]},
            ]
        }
        assert vt.find_video_track(project, "vt1")["id"] == "vt1"
        track, clip = vt.find_clip(project, "c1")
        assert track["id"] == "vt1" and clip["id"] == "c1"
        with pytest.raises(vt.VideoTrackError, match="no such video track"):
            vt.find_video_track(project, "ghost")
        with pytest.raises(vt.VideoTrackError, match="no such video clip"):
            vt.find_clip(project, "ghost")

    def test_add_lane_is_idempotent_and_auto_indexes(self):
        project: dict[str, Any] = {}
        first = vt.add_video_track(project, {"id": "vt1"}, fps=30)
        assert first["index"] == 0
        assert vt.add_video_track(project, {"id": "vt1"}, fps=30) is first
        second = vt.add_video_track(project, {}, fps=30)
        assert second["index"] == 1
        assert len(vt.video_tracks_of(project)) == 2

    def test_remove_lane_returns_it_and_raises_when_absent(self):
        project: dict[str, Any] = {}
        vt.add_video_track(project, {"id": "vt1"}, fps=30)
        assert vt.remove_video_track(project, "vt1")["id"] == "vt1"
        assert vt.video_tracks_of(project) == []
        with pytest.raises(vt.VideoTrackError, match="no such video track"):
            vt.remove_video_track(project, "vt1")

    def test_add_clip_refuses_an_id_collision_and_an_overlap(self):
        project: dict[str, Any] = {}
        vt.add_video_track(project, {"id": "vt1"}, fps=30)
        vt.add_clip(project, "vt1", a_clip(), fps=30)
        with pytest.raises(vt.VideoTrackError, match="already exists"):
            vt.add_clip(project, "vt1", a_clip(), fps=30)
        with pytest.raises(vt.VideoTrackError, match="overlap"):
            vt.add_clip(project, "vt1", a_clip(id="c2", timelineStart=1.0), fps=30)
        # abutting is legal (the normal result of a razor cut)
        assert vt.add_clip(project, "vt1", a_clip(id="c3", timelineStart=2.0), fps=30)["id"] == "c3"

    def test_remove_clip_returns_it(self):
        project: dict[str, Any] = {}
        vt.add_video_track(project, {"id": "vt1"}, fps=30)
        vt.add_clip(project, "vt1", a_clip(), fps=30)
        assert vt.remove_clip(project, "c1")["id"] == "c1"
        assert vt.find_video_track(project, "vt1")["clips"] == []

    def test_replace_clip_preserves_lane_position_and_raises_when_absent(self):
        track = vt.normalize_video_track(
            {
                "id": "vt1",
                "clips": [
                    a_clip(id="c1", timelineStart=0.0),
                    a_clip(id="c2", timelineStart=2.0),
                    a_clip(id="c3", timelineStart=4.0),
                ],
            },
            fps=30,
        )
        vt.replace_clip(track, "c2", [a_clip(id="x1", timelineStart=2.0)])
        assert [c["id"] for c in track["clips"]] == ["c1", "x1", "c3"]
        with pytest.raises(vt.VideoTrackError, match="no such video clip"):
            vt.replace_clip(track, "ghost", [])

    def test_bad_trim_edge_is_refused(self):
        with pytest.raises(vt.VideoTrackError, match="edge must be one of"):
            vt.trim_clip_edge(vt.normalize_video_clip(a_clip(), fps=30), "middle", 1.0, fps=30)

    def test_a_head_trim_that_eats_the_whole_clip_is_refused(self):
        clip = vt.normalize_video_clip(a_clip(srcIn=0.0, srcOut=2.0, timelineStart=0.0), fps=30)
        with pytest.raises(vt.VideoTrackError, match="at least"):
            vt.trim_clip_edge(clip, "start", 2.0, fps=30)

    def test_trim_before_the_source_head_is_refused(self):
        clip = vt.normalize_video_clip(a_clip(srcIn=0.5, srcOut=2.0, timelineStart=5.0), fps=30)
        with pytest.raises(vt.VideoTrackError, match="before the source"):
            vt.trim_clip_edge(clip, "start", 4.0, fps=30)

    def test_negative_move_is_refused_not_clamped(self):
        with pytest.raises(vt.VideoTrackError, match=">= 0"):
            vt.move_clip(vt.normalize_video_clip(a_clip(), fps=30), -1.0, fps=30)

    def test_flatten_rejects_a_non_object_lane(self):
        with pytest.raises(vt.VideoTrackError, match="must be an object"):
            vt.flatten_timeline(["junk"], fps=30)  # type: ignore[list-item]

    def test_timeline_duration_sums_the_segments(self):
        segments = vt.flatten_timeline(
            [
                vt.normalize_video_track(
                    {
                        "id": "vt1",
                        # a GAP between the two clips: concat closes it (documented)
                        "clips": [a_clip(id="c1"), a_clip(id="c2", timelineStart=10.0)],
                    },
                    fps=30,
                )
            ],
            fps=30,
        )
        assert vt.timeline_duration(segments) == pytest.approx(4.0)


# --------------------------------------------------------------------------- #
# the service — a REAL on-disk JSON store
# --------------------------------------------------------------------------- #
class DiskStore:
    """A minimal per-video JSON project store (what the composition root binds)."""

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


def make_service(tmp_path: Path, *, run=None, duration=None, settings=None):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake container")
    disk = DiskStore(tmp_path / "projects")
    service = vt.VideoTracksService(
        resolver=lambda vid: str(video) if vid == "v1" else None,
        load_project=disk.load,
        save_project=disk.save,
        out_dir=tmp_path / "exports" / "timeline",
        settings_provider=(lambda: SETTINGS) if settings is None else settings,
        run=run or (lambda argv, **kw: 0),
        duration=duration or (lambda path, settings=None: 60.0),
    )
    return service, disk, video


class TestServiceList:
    def test_list_seeds_the_base_lane_from_the_source_duration(self, tmp_path: Path):
        service, disk, video = make_service(tmp_path)
        result = service.list({"videoId": "v1"}, ctx())
        assert result["fps"] == vt.DEFAULT_FPS
        lanes = result["videoTracks"]
        assert len(lanes) == 1 and lanes[0]["index"] == 0 and lanes[0]["name"] == "Video 1"
        clip = lanes[0]["clips"][0]
        assert clip["path"] == str(video)
        assert (clip["srcIn"], clip["srcOut"], clip["timelineStart"]) == (0.0, 60.0, 0.0)
        # persisted, so the seed happens exactly once
        assert disk.load("v1")["videoTracks"][0]["clips"][0]["id"] == clip["id"]
        assert service.list({"videoId": "v1"}, ctx())["videoTracks"][0]["clips"][0]["id"] == clip["id"]

    def test_an_unprobeable_source_seeds_an_EMPTY_lane_never_a_guessed_length(self, tmp_path: Path, monkeypatch):
        warnings: list[tuple] = []
        monkeypatch.setattr(vt.log, "warning", lambda *a, **k: warnings.append(a))
        service, _disk, _video = make_service(tmp_path, duration=lambda p, settings=None: 0.0)
        lanes = service.list({"videoId": "v1"}, ctx())["videoTracks"]
        assert lanes[0]["clips"] == []
        assert any("EMPTY base lane" in w[0] for w in warnings)

    def test_a_raising_duration_probe_degrades_loudly(self, tmp_path: Path, monkeypatch):
        warnings: list[tuple] = []
        monkeypatch.setattr(vt.log, "warning", lambda *a, **k: warnings.append(a))

        def boom(path, settings=None):
            raise OSError("ffprobe gone")

        service, _disk, _video = make_service(tmp_path, duration=boom)
        assert service.list({"videoId": "v1"}, ctx())["videoTracks"][0]["clips"] == []
        assert any("duration probe failed" in w[0] for w in warnings)

    def test_unknown_video_and_missing_param_are_typed_refusals(self, tmp_path: Path):
        service, _disk, _video = make_service(tmp_path)
        with pytest.raises(RpcError, match="videoId"):
            service.list({}, ctx())
        with pytest.raises(RpcError, match="unknown video"):
            service.list({"videoId": "ghost"}, ctx())

    def test_a_bad_explicit_fps_is_a_typed_refusal(self, tmp_path: Path):
        service, _disk, _video = make_service(tmp_path)
        with pytest.raises(RpcError, match="unsupported fps"):
            service.list({"videoId": "v1", "fps": 29.97}, ctx())

    def test_a_broken_settings_provider_never_breaks_an_edit(self, tmp_path: Path):
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings store on fire")

        service, _disk, _video = make_service(tmp_path, settings=boom)
        assert service.list({"videoId": "v1"}, ctx())["fps"] == vt.DEFAULT_FPS

    def test_a_corrupt_persisted_lane_list_is_a_typed_refusal(self, tmp_path: Path):
        service, disk, _video = make_service(tmp_path)
        disk.save("v1", {"videoTracks": {"not": "a list"}})
        with pytest.raises(RpcError, match="videoTracks must be a list"):
            service.list({"videoId": "v1"}, ctx())

    def test_malformed_rows_in_a_hand_edited_manifest_are_skipped_not_fatal(self, tmp_path: Path, registry):
        """A junk lane/clip row must not become an opaque internal error.

        ``find_clip`` and ``library.py``'s ref walk both skip non-dict rows, so a
        hand-edited manifest carrying one is a real possibility. The read path has
        to agree with them: ``dict("junk")`` raises ValueError, which is NOT a
        VideoTrackError and would surface as a 500 instead of a typed refusal.
        """
        service, disk, video = make_service(tmp_path)
        disk.save(
            "v1",
            {
                "videoTracks": [
                    "not-a-lane",
                    {
                        "id": "vt1",
                        "name": "Video 1",
                        "index": 0,
                        "clips": [
                            "not-a-clip",
                            {"id": "c1", "path": str(video), "srcIn": 0.0, "srcOut": 2.0, "timelineStart": 0.0},
                        ],
                    },
                ]
            },
        )
        lanes = service.list({"videoId": "v1"}, ctx())["videoTracks"]
        assert [t["id"] for t in lanes] == ["vt1"]
        assert [c["id"] for c in lanes[0]["clips"]] == ["c1"]
        # ... and the render path agrees, rather than choking on the same row
        job = registry.get(service.render({"videoId": "v1"}, job_ctx(registry))["jobId"])
        job.wait(timeout=10)
        assert job.error is None
        assert [s["clipId"] for s in job.result["segments"]] == ["c1"]


class TestServiceLanes:
    def test_add_lane_appends_at_the_next_index(self, tmp_path: Path):
        service, _disk, _video = make_service(tmp_path)
        service.list({"videoId": "v1"}, ctx())
        lane = service.add_lane({"videoId": "v1"}, ctx())["videoTrack"]
        assert lane["index"] == 1 and lane["name"] == "Video 2"
        named = service.add_lane({"videoId": "v1", "name": "B-roll"}, ctx())["videoTrack"]
        assert named["index"] == 2 and named["name"] == "B-roll"

    def test_add_lane_rejects_a_corrupt_lane_list(self, tmp_path: Path):
        service, disk, _video = make_service(tmp_path)
        disk.save("v1", {"videoTracks": "junk"})
        with pytest.raises(RpcError, match="videoTracks must be a list"):
            service.add_lane({"videoId": "v1"}, ctx())

    def test_remove_lane_reports_what_it_took_with_it(self, tmp_path: Path):
        service, _disk, _video = make_service(tmp_path)
        lanes = service.list({"videoId": "v1"}, ctx())["videoTracks"]
        result = service.remove_lane({"videoId": "v1", "videoTrackId": lanes[0]["id"]}, ctx())
        assert result == {"removed": lanes[0]["id"], "clips": 1}

    def test_remove_unknown_lane_is_a_typed_refusal(self, tmp_path: Path):
        service, _disk, _video = make_service(tmp_path)
        service.list({"videoId": "v1"}, ctx())
        with pytest.raises(RpcError, match="no such video track"):
            service.remove_lane({"videoId": "v1", "videoTrackId": "ghost"}, ctx())


class TestServiceClips:
    def _seeded(self, tmp_path: Path, **kw):
        service, disk, video = make_service(tmp_path, **kw)
        lanes = service.list({"videoId": "v1"}, ctx())["videoTracks"]
        return service, disk, video, lanes[0]["id"], lanes[0]["clips"][0]["id"]

    def test_add_clip_places_a_second_source_on_a_second_lane(self, tmp_path: Path):
        service, _disk, _video, _lane, _clip = self._seeded(tmp_path)
        broll = tmp_path / "broll.mp4"
        broll.write_bytes(b"b")
        lane2 = service.add_lane({"videoId": "v1", "name": "B-roll"}, ctx())["videoTrack"]["id"]
        clip = service.add_clip(
            {
                "videoId": "v1",
                "videoTrackId": lane2,
                "path": str(broll),
                "srcIn": 1.0,
                "srcOut": 3.0,
                "timelineStart": 70.0,
            },
            ctx(),
        )["clip"]
        assert clip["path"] == str(broll)
        assert (clip["srcIn"], clip["srcOut"], clip["timelineStart"]) == (1.0, 3.0, 70.0)

    def test_add_clip_validates_every_param(self, tmp_path: Path):
        service, _disk, _video, lane, _clip = self._seeded(tmp_path)
        base = {"videoId": "v1", "videoTrackId": lane, "srcIn": 0.0, "srcOut": 1.0, "timelineStart": 0.0}
        with pytest.raises(RpcError, match="path"):
            service.add_clip({**base}, ctx())
        with pytest.raises(RpcError, match="source file not found"):
            service.add_clip({**base, "path": str(tmp_path / "nope.mp4")}, ctx())
        with pytest.raises(RpcError, match="srcIn"):
            service.add_clip({**base, "path": "x", "srcIn": True}, ctx())
        with pytest.raises(RpcError, match="srcOut"):
            service.add_clip({**base, "path": "x", "srcOut": "1"}, ctx())
        with pytest.raises(RpcError, match="timelineStart"):
            service.add_clip({**base, "path": "x", "timelineStart": None}, ctx())

    def test_add_clip_refuses_a_window_past_the_source_end(self, tmp_path: Path):
        service, _disk, video, lane, _clip = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="runs past the end"):
            service.add_clip(
                {
                    "videoId": "v1",
                    "videoTrackId": lane,
                    "path": str(video),
                    "srcIn": 0.0,
                    "srcOut": 999.0,
                    "timelineStart": 200.0,
                },
                ctx(),
            )

    def test_an_unprobeable_source_skips_the_length_check(self, tmp_path: Path):
        """duration 0 == probe unavailable -> the bound check is SKIPPED, not faked.

        A probe that cannot answer must not become a false refusal (nor a false
        pass that is silent about it — ``_probe_duration`` logs the degradation).
        """
        service, _disk, video = make_service(tmp_path, duration=lambda p, settings=None: 0.0)
        service.list({"videoId": "v1"}, ctx())  # seeds an EMPTY lane (no usable duration)
        lane = service.add_lane({"videoId": "v1"}, ctx())["videoTrack"]["id"]
        clip = service.add_clip(
            {
                "videoId": "v1",
                "videoTrackId": lane,
                "path": str(video),
                "srcIn": 0.0,
                "srcOut": 999.0,  # unverifiable, so ACCEPTED rather than wrongly refused
                "timelineStart": 0.0,
            },
            ctx(),
        )["clip"]
        assert clip["srcOut"] == pytest.approx(999.0)

    def test_add_clip_onto_an_unknown_lane_is_a_typed_refusal(self, tmp_path: Path):
        service, _disk, video, _lane, _clip = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="no such video track"):
            service.add_clip(
                {
                    "videoId": "v1",
                    "videoTrackId": "ghost",
                    "path": str(video),
                    "srcIn": 0.0,
                    "srcOut": 1.0,
                    "timelineStart": 0.0,
                },
                ctx(),
            )

    def test_trim_persists_and_keeps_the_invariant(self, tmp_path: Path):
        service, disk, _video, _lane, clip_id = self._seeded(tmp_path)
        trimmed = service.trim_clip({"videoId": "v1", "clipId": clip_id, "edge": "end", "timelineTime": 10.0}, ctx())[
            "clip"
        ]
        assert trimmed["srcOut"] == pytest.approx(10.0)
        stored = disk.load("v1")["videoTracks"][0]["clips"][0]
        assert stored["srcOut"] == pytest.approx(10.0)
        assert vt.frame_span(stored, 30) == vt.frame_source_span(stored, 30)

    def test_trim_validates_params_and_reports_an_illegal_edit(self, tmp_path: Path):
        service, _disk, _video, _lane, clip_id = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="clipId"):
            service.trim_clip({"videoId": "v1"}, ctx())
        with pytest.raises(RpcError, match="edge"):
            service.trim_clip({"videoId": "v1", "clipId": clip_id}, ctx())
        with pytest.raises(RpcError, match="timelineTime"):
            service.trim_clip({"videoId": "v1", "clipId": clip_id, "edge": "end"}, ctx())
        with pytest.raises(RpcError, match="at least"):
            service.trim_clip({"videoId": "v1", "clipId": clip_id, "edge": "end", "timelineTime": 0.0}, ctx())
        with pytest.raises(RpcError, match="no such video clip"):
            service.trim_clip({"videoId": "v1", "clipId": "ghost", "edge": "end", "timelineTime": 5.0}, ctx())

    def test_split_persists_two_abutting_clips_in_lane_order(self, tmp_path: Path):
        service, disk, _video, _lane, clip_id = self._seeded(tmp_path)
        halves = service.split_clip({"videoId": "v1", "clipId": clip_id, "atTimeline": 20.0}, ctx())["clips"]
        assert [h["id"] for h in halves][0] == clip_id
        stored = disk.load("v1")["videoTracks"][0]["clips"]
        assert len(stored) == 2
        assert vt.clip_timeline_end(stored[0]) == pytest.approx(stored[1]["timelineStart"])

    def test_split_outside_the_clip_is_a_typed_refusal(self, tmp_path: Path):
        service, _disk, _video, _lane, clip_id = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="atTimeline"):
            service.split_clip({"videoId": "v1", "clipId": clip_id}, ctx())
        with pytest.raises(RpcError, match="inside the clip"):
            service.split_clip({"videoId": "v1", "clipId": clip_id, "atTimeline": 999.0}, ctx())

    def test_move_slides_within_the_lane(self, tmp_path: Path):
        service, disk, _video, _lane, clip_id = self._seeded(tmp_path)
        moved = service.move_clip({"videoId": "v1", "clipId": clip_id, "timelineStart": 5.0}, ctx())["clip"]
        assert moved["timelineStart"] == pytest.approx(5.0)
        assert disk.load("v1")["videoTracks"][0]["clips"][0]["timelineStart"] == pytest.approx(5.0)

    def test_move_validates_params_and_refuses_a_negative_slide(self, tmp_path: Path):
        service, _disk, _video, _lane, clip_id = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="timelineStart"):
            service.move_clip({"videoId": "v1", "clipId": clip_id}, ctx())
        with pytest.raises(RpcError, match=">= 0"):
            service.move_clip({"videoId": "v1", "clipId": clip_id, "timelineStart": -1.0}, ctx())

    def test_move_onto_a_clip_already_there_is_refused_not_overwritten(self, tmp_path: Path):
        service, _disk, _video, _lane, clip_id = self._seeded(tmp_path)
        halves = service.split_clip({"videoId": "v1", "clipId": clip_id, "atTimeline": 20.0}, ctx())["clips"]
        with pytest.raises(RpcError, match="overlap"):
            service.move_clip({"videoId": "v1", "clipId": halves[1]["id"], "timelineStart": 0.0}, ctx())

    def test_move_across_lanes_reparents_the_clip(self, tmp_path: Path):
        service, disk, _video, lane, clip_id = self._seeded(tmp_path)
        lane2 = service.add_lane({"videoId": "v1", "name": "B-roll"}, ctx())["videoTrack"]["id"]
        result = service.move_clip(
            {"videoId": "v1", "clipId": clip_id, "timelineStart": 3.0, "videoTrackId": lane2}, ctx()
        )
        assert result["videoTrackId"] == lane2
        stored = {t["id"]: t["clips"] for t in disk.load("v1")["videoTracks"]}
        assert stored[lane] == []
        assert [c["id"] for c in stored[lane2]] == [clip_id]
        assert stored[lane2][0]["timelineStart"] == pytest.approx(3.0)

    def test_move_across_lanes_refuses_an_unknown_target_or_an_overlap(self, tmp_path: Path):
        service, _disk, _video, lane, clip_id = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="no such video track"):
            service.move_clip(
                {"videoId": "v1", "clipId": clip_id, "timelineStart": 0.0, "videoTrackId": "ghost"}, ctx()
            )
        with pytest.raises(RpcError, match="no such video clip"):
            service.move_clip({"videoId": "v1", "clipId": "ghost", "timelineStart": 0.0, "videoTrackId": lane}, ctx())
        halves = service.split_clip({"videoId": "v1", "clipId": clip_id, "atTimeline": 20.0}, ctx())["clips"]
        with pytest.raises(RpcError, match="overlap"):
            service.move_clip(
                {"videoId": "v1", "clipId": halves[1]["id"], "timelineStart": 0.0, "videoTrackId": lane}, ctx()
            )

    def test_remove_clip_persists_the_removal(self, tmp_path: Path):
        service, disk, _video, _lane, clip_id = self._seeded(tmp_path)
        assert service.remove_clip({"videoId": "v1", "clipId": clip_id}, ctx()) == {"removed": clip_id}
        assert disk.load("v1")["videoTracks"][0]["clips"] == []
        with pytest.raises(RpcError, match="no such video clip"):
            service.remove_clip({"videoId": "v1", "clipId": clip_id}, ctx())


class TestServiceRender:
    """``render`` must be a JOB, not a blocking direct handler.

    An encode of a long timeline takes minutes; running it inside the handler
    would block the sidecar's single stdio loop and freeze the whole app (the
    reason every other encode feature — stabilize.run, audiomix.merge,
    silence.trim — returns ``{jobId}``). It must also be cooperatively
    cancellable, since a user who mis-cut the timeline needs to stop the encode.
    """

    def _seeded(self, tmp_path: Path, **kw):
        service, disk, video = make_service(tmp_path, **kw)
        lanes = service.list({"videoId": "v1"}, ctx())["videoTracks"]
        return service, disk, video, lanes[0]["id"], lanes[0]["clips"][0]["id"]

    def test_render_defers_to_a_job_and_reports_the_output(self, tmp_path: Path, registry):
        calls: list[tuple] = []
        service, _disk, video, _lane, clip_id = self._seeded(
            tmp_path, run=lambda argv, **kw: calls.append((argv, kw)) or 0
        )
        service.split_clip({"videoId": "v1", "clipId": clip_id, "atTimeline": 20.0}, ctx())
        handle = service.render({"videoId": "v1"}, job_ctx(registry))
        assert set(handle) == {"jobId"}
        job = registry.get(handle["jobId"])
        job.wait(timeout=10)
        result = job.result
        assert result["durationSec"] == pytest.approx(60.0)
        assert len(result["segments"]) == 2
        assert Path(result["path"]).parent == tmp_path / "exports" / "timeline"
        argv, kw = calls[0]
        assert argv[0] == "/bin/ffmpeg"
        assert argv[-1] == result["path"]
        assert argv.count("-i") == 1 and argv[argv.index("-i") + 1] == str(video)
        assert kw["total_sec"] == pytest.approx(60.0)

    def test_render_without_a_job_registry_is_a_typed_refusal(self, tmp_path: Path):
        service, _disk, _video, _lane, _clip = self._seeded(tmp_path)
        with pytest.raises(RpcError, match="job registry"):
            service.render({"videoId": "v1"}, ctx())

    def test_a_nonzero_ffmpeg_exit_fails_the_job_not_a_silent_pass(self, tmp_path: Path, registry):
        service, _disk, _video, _lane, _clip = self._seeded(tmp_path, run=lambda argv, **kw: 3)
        job = registry.get(service.render({"videoId": "v1"}, job_ctx(registry))["jobId"])
        job.wait(timeout=10)
        assert job.error is not None and "ffmpeg exit 3" in str(job.error)

    def test_render_refuses_an_empty_timeline_before_starting_a_job(self, tmp_path: Path, registry):
        service, _disk, _video, _lane, clip_id = self._seeded(tmp_path)
        service.remove_clip({"videoId": "v1", "clipId": clip_id}, ctx())
        with pytest.raises(RpcError, match="at least one"):
            service.render({"videoId": "v1"}, job_ctx(registry))

    def test_render_refuses_an_overlapping_timeline_before_starting_a_job(self, tmp_path: Path, registry):
        service, disk, video, _lane, _clip = self._seeded(tmp_path)
        data = disk.load("v1")
        data["videoTracks"][0]["clips"].append(
            {"id": "c2", "path": str(video), "srcIn": 0.0, "srcOut": 5.0, "timelineStart": 1.0}
        )
        disk.save("v1", data)
        with pytest.raises(RpcError, match="overlap"):
            service.render({"videoId": "v1"}, job_ctx(registry))

    def test_the_job_body_passes_a_cancel_probe_and_a_progress_sink_to_ffmpeg(self, tmp_path: Path, registry) -> None:
        """Cooperative cancel + progress are WIRED, asserted on the seam's kwargs.

        UNVERIFIED (inline, scoped): this proves the ``should_cancel`` callable and
        the ``on_progress`` sink reach ``ffmpeg.run``; it does NOT prove ffmpeg is
        actually killed mid-encode. That is a property of the shipped drained
        runner (``ffmpeg.run`` + ``_watch_cancel``, already covered by
        tests/test_ffmpeg.py), not of this module. Settling experiment for the
        end-to-end claim: an ``e2e``-marked test that renders a long real clip and
        cancels the job, asserting the process exits and the partial file is
        removed. Not written here — this module owns no process handling.
        """
        seen: list[dict[str, Any]] = []
        service, _disk, _video, _lane, _clip = self._seeded(tmp_path, run=lambda argv, **kw: seen.append(kw) or 0)
        job = registry.get(service.render({"videoId": "v1"}, job_ctx(registry))["jobId"])
        job.wait(timeout=10)
        assert callable(seen[0]["should_cancel"]) and seen[0]["should_cancel"]() is False
        assert callable(seen[0]["on_progress"])
        # the progress sink is a real pass-through onto the job's own reporter
        seen[0]["on_progress"](42, "half way")


class TestRegistration:
    def test_register_wires_the_nine_frozen_names(self, tmp_path: Path):
        registered: dict[str, Any] = {}
        video = tmp_path / "v.mp4"
        video.write_bytes(b"v")
        service = vt.register(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            out_dir=tmp_path / "out",
            settings_provider=lambda: SETTINGS,
            run=lambda argv, **kw: 0,
            duration=lambda p, settings=None: 1.0,
            register_fn=lambda name, handler: registered.__setitem__(name, handler),
        )
        assert isinstance(service, vt.VideoTracksService)
        assert sorted(registered) == [
            "tracks.video.addClip",
            "tracks.video.addLane",
            "tracks.video.list",
            "tracks.video.moveClip",
            "tracks.video.removeClip",
            "tracks.video.removeLane",
            "tracks.video.render",
            "tracks.video.splitClip",
            "tracks.video.trimClip",
        ]

    def test_default_seams_are_the_real_ffmpeg_helpers(self, tmp_path: Path):
        service = vt.VideoTracksService(
            resolver=lambda vid: None,
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            out_dir=tmp_path,
        )
        assert service._run is ffmpeg.run
        assert service._duration is ffmpeg.ffprobe_duration
        assert service._settings() == {}
        # the per-video lock is created once and reused (the manifest critical section)
        assert service._lock_for("v1") is service._lock_for("v1")
