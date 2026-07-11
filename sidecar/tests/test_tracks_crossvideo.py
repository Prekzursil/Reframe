"""Cross-video tracks.add re-issues a fresh track id (bug-sweep fix).

tracks.add copies a track from the project that owns it onto a DIFFERENT video's
project. It used to preserve the source id, so the same id lived in two
manifests — and a later trackId-only op (rename/relabel/subtitles.edit/export)
resolved to whichever manifest sorts first (the wrong video). The copy now gets
a fresh id so it is independently addressable.
"""

from __future__ import annotations

from pathlib import Path

from media_studio.handlers import Services
from media_studio.protocol import RpcContext


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def test_tracks_add_cross_video_reissues_fresh_id(tmp_path: Path) -> None:
    from media_studio import library as _lib

    svc = Services(data_dir=tmp_path / "d")
    fa = tmp_path / "a.mp4"
    fb = tmp_path / "b.mp4"
    fa.write_bytes(b"\x00")
    fb.write_bytes(b"\x00")
    svc.library = _lib.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 1.0)
    vid_a = svc.library.add(str(fa))["id"]
    vid_b = svc.library.add(str(fb))["id"]

    proj_a = svc._load_or_create_project(vid_a)
    proj_a.data["tracks"] = [{"id": "T", "kind": "soft", "lang": "en", "name": "orig", "cues": []}]
    proj_a.save()
    svc._load_or_create_project(vid_b).save()

    svc.tracks_add({"videoId": vid_b, "trackId": "T"}, _ctx())

    b_tracks = svc._load_or_create_project(vid_b).data.get("tracks") or []
    assert len(b_tracks) == 1, "the track was not copied into video B"
    assert b_tracks[0]["id"] != "T", "cross-video copy kept the source id (ambiguous resolution)"
    assert b_tracks[0]["name"] == "orig", "the track content was not copied"
    # Video A's original track is untouched and its id stays unique to A.
    a_tracks = svc._load_or_create_project(vid_a).data.get("tracks") or []
    assert [t["id"] for t in a_tracks] == ["T"]
