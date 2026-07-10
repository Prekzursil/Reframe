"""Project consolidate / find_missing_sources include dub AudioTracks (bug-sweep fix).

A project's dub-audio files live under ``Project.audioTracks[*].path`` but
``_ref_paths`` (find_missing_sources) and ``consolidate`` only walked
video/clips/tracks — so a portable copy silently dropped the dub audio and a
deleted dub was never reported as missing. Both now include audioTracks.
"""

from __future__ import annotations

from pathlib import Path

from media_studio.library import Project


def test_find_missing_sources_flags_missing_dub_audio(tmp_path: Path) -> None:
    proj = Project(
        {"video": {"path": "v.mp4"}, "audioTracks": [{"id": "d1", "path": "dub_fr.m4a"}]},
        manifest_path=tmp_path / "project.json",
    )
    missing = proj.find_missing_sources()
    assert "dub_fr.m4a" in missing, "a missing dub-audio file was not reported by find_missing_sources"


def test_consolidate_copies_and_rebases_dub_audio(tmp_path: Path) -> None:
    src = tmp_path / "dub_fr.m4a"
    src.write_bytes(b"dubaudio")
    proj = Project(
        {"video": {}, "audioTracks": [{"id": "d1", "path": str(src)}]},
        manifest_path=tmp_path / "project.json",
    )
    out = proj.consolidate(tmp_path / "portable")
    rebased = proj.data["audioTracks"][0]["path"]
    assert rebased.startswith("assets/"), "dub-audio path was not rebased into the portable folder"
    assert (Path(out) / rebased).exists(), "dub-audio file was not copied into the portable folder"
