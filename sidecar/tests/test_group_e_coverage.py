"""Targeted coverage tests for the group-E feature modules.

These fill the last uncovered lines/branches in:
  - features/tracks_audio.py  - features/tracks.py
  - features/subtitles.py     - features/caption.py
  - features/caption_remotion.py - features/timeline.py
  - features/fillers.py

Every test exercises a REAL code path through the modules' injectable seams
(no heavy-ML imports, no real subprocess). The style mirrors the existing
per-module test files (recording fakes for the ffmpeg ``run`` / ``popen`` seams,
tmp-dir filesystem probes, in-memory project stores).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg, protocol
from media_studio.features import caption as cap
from media_studio.features import caption_remotion as cr
from media_studio.features import fillers as fl
from media_studio.features import subtitles as S
from media_studio.features import timeline as tl
from media_studio.features import tracks as tr
from media_studio.features import tracks_audio as ta
from media_studio.protocol import RpcContext, RpcError


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# =========================================================================== #
# tracks_audio.py
# =========================================================================== #
class TestTracksAudioGaps:
    def test_require_str_rejects_missing(self):
        # line 89: _require_str raises on a missing/empty value.
        with pytest.raises(RpcError, match="videoId"):
            ta._require_str({}, "videoId")
        with pytest.raises(RpcError, match="videoId"):
            ta._require_str({"videoId": ""}, "videoId")

    def test_normalize_rejects_non_dict(self):
        # line 104: normalize_audio_track on a non-dict.
        with pytest.raises(ta.AudioTrackError, match="must be an object"):
            ta.normalize_audio_track("not a dict")  # type: ignore[arg-type]

    def test_audio_tracks_of_rejects_non_list(self):
        # line 124: a project whose audioTracks is not a list.
        with pytest.raises(ta.AudioTrackError, match="must be a list"):
            ta.audio_tracks_of({"audioTracks": "nope"})

    def test_audio_track_index_unknown_raises(self):
        # line 141: audio_track_index when the id is absent.
        with pytest.raises(ta.AudioTrackError, match="no such audio track"):
            ta.audio_track_index({"audioTracks": []}, "ghost")

    def test_mux_argv_without_lang_omits_metadata(self):
        # branch 200->202: lang falsy -> no -metadata:s:a:N pair appended.
        argv = ta.build_mux_argv("in.mkv", "a.m4a", "out.mkv", lang=None, existing_audio_count=0)
        assert not any(a.startswith("-metadata:s:a") for a in argv)
        assert argv[-1] == "out.mkv"

    def test_replace_argv_without_lang_omits_metadata(self):
        # branch 241->243: lang falsy on replace -> no -metadata:s:a pair.
        argv = ta.build_replace_argv("in.mkv", "a.m4a", "out.mkv", stream_index=0, lang=None)
        assert not any(a.startswith("-metadata:s:a") for a in argv)

    def test_probe_streams_real_subprocess_seam(self, monkeypatch):
        # lines 290-306: drive probe_streams through a fake subprocess runner.
        monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")

        class _Completed:
            def __init__(self, returncode: int, stdout: str) -> None:
                self.returncode = returncode
                self.stdout = stdout

        good = {"streams": [{"codec_type": "audio"}]}
        runner_calls: list[list[str]] = []

        def runner(argv, **kwargs):
            runner_calls.append(list(argv))
            return _Completed(0, json.dumps(good))

        out = ta.probe_streams("v.mkv", {}, runner=runner)
        assert out == good
        assert runner_calls and "-show_streams" in runner_calls[0]

        # non-zero return -> {}
        assert ta.probe_streams("v.mkv", {}, runner=lambda *a, **k: _Completed(1, "x")) == {}
        # invalid JSON -> {}
        assert ta.probe_streams("v.mkv", {}, runner=lambda *a, **k: _Completed(0, "{not json")) == {}
        # JSON that is not a dict -> {}
        assert ta.probe_streams("v.mkv", {}, runner=lambda *a, **k: _Completed(0, "[1,2]")) == {}

    def test_settings_provider_crash_falls_back(self, tmp_path):
        # lines 366-367: a crashing settings provider -> {}.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")

        def boom() -> dict[str, Any]:
            raise RuntimeError("settings on fire")

        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            settings_provider=boom,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=lambda path, settings=None: {},
        )
        assert service._settings() == {}

    def test_seed_originals_probe_crash_is_soft(self, tmp_path):
        # lines 382-384: a probe that raises -> no originals, no 500.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")

        def probe_boom(path, settings=None):
            raise RuntimeError("ffprobe crashed")

        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=probe_boom,
        )
        project: dict[str, Any] = {}
        assert service._seed_originals(project, "v1", str(video)) is False

    def test_seed_originals_empty_probe_seeds_nothing(self, tmp_path):
        # line 387: probe returns no audio streams -> no change.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")
        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=lambda path, settings=None: {"streams": [{"codec_type": "video"}]},
        )
        assert service._seed_originals({}, "v1", str(video)) is False

    def test_run_or_raise_duration_probe_crash_is_soft(self, tmp_path):
        # lines 396-397: a duration probe crash only coarsens progress.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")
        ran: list[float] = []

        def duration_boom(path, settings=None):
            raise RuntimeError("probe crashed")

        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            run=lambda argv, total_sec=0.0, **kw: ran.append(total_sec) or 0,
            duration=duration_boom,
            probe=lambda path, settings=None: {},
        )
        service._run_or_raise(["ffmpeg"], str(video), "test op")
        assert ran == [0.0]  # crashed probe -> coarse 0.0 total

    def test_mux_surfaces_audio_track_error_as_invalid(self, tmp_path, monkeypatch):
        # line 430: a bad kind inside _mux_impl raises AudioTrackError -> INVALID_PARAMS.
        monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")
        dub = tmp_path / "dub.m4a"
        dub.write_bytes(b"a")
        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {},
            save_project=lambda vid, data: None,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=lambda path, settings=None: {},
        )
        with pytest.raises(RpcError) as exc:
            service.mux(
                {"videoId": "v1", "path": str(dub), "lang": "de", "name": "x", "kind": "hard"},
                _ctx(),
            )
        assert exc.value.code == protocol.ErrorCode.INVALID_PARAMS

    def test_replace_missing_audio_file_rejected(self, tmp_path):
        # line 439: replace with a non-existent audio path.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")
        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {"audioTracks": []},
            save_project=lambda vid, data: None,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=lambda path, settings=None: {},
        )
        with pytest.raises(RpcError, match="not found"):
            service.replace(
                {"videoId": "v1", "audioTrackId": "t", "path": str(tmp_path / "ghost.m4a")},
                _ctx(),
            )

    def test_strip_unknown_track_rejected(self, tmp_path):
        # lines 469-470: strip with an unknown audioTrackId.
        video = tmp_path / "v.mkv"
        video.write_bytes(b"x")
        service = ta.AudioTracksService(
            resolver=lambda vid: str(video),
            load_project=lambda vid: {"audioTracks": []},
            save_project=lambda vid, data: None,
            run=lambda argv, **kw: 0,
            duration=lambda path, settings=None: 0.0,
            probe=lambda path, settings=None: {},
        )
        with pytest.raises(RpcError, match="no such audio track"):
            service.strip({"videoId": "v1", "audioTrackId": "ghost"}, _ctx())


# =========================================================================== #
# tracks.py
# =========================================================================== #
class TestTracksGaps:
    def test_tracks_of_rejects_non_list(self):
        # line 87: a project whose tracks is not a list.
        with pytest.raises(tr.TrackError, match="must be a list"):
            tr._tracks_of({"tracks": "nope"})

    def test_add_track_idempotent_on_existing_id(self):
        # An existing id short-circuits without appending (the return path).
        project: dict[str, Any] = {}
        first = tr.add_track(project, {"id": "t1", "kind": "soft"})
        again = tr.add_track(project, {"id": "t1", "kind": "soft"})
        assert again is first
        assert len(project["tracks"]) == 1

    def test_add_track_iterates_past_non_matching_id(self):
        # branch 116->115: a DIFFERENT existing track is skipped (loop continues)
        # and the new track is appended at the end.
        project: dict[str, Any] = {}
        tr.add_track(project, {"id": "t1", "kind": "soft"})
        new = tr.add_track(project, {"id": "t2", "kind": "soft"})
        assert new["id"] == "t2"
        assert [t["id"] for t in project["tracks"]] == ["t1", "t2"]


# =========================================================================== #
# subtitles.py
# =========================================================================== #
class TestSubtitlesGaps:
    def test_split_segment_skips_blank_flush(self):
        # lines 159/161->exit: flush() is called with a cur holding only
        # blank-text words -> joined text is "" -> `if text` is False -> no cue.
        # A leading blank word accumulates, then a long real word forces a flush
        # of the (all-blank) cur before the real word is packed.
        words = [
            {"text": "   ", "start": 0.0, "end": 0.5},
            {"text": "realword", "start": 5.0, "end": 6.0},
        ]
        cues = S._split_segment(words, max_chars=3, max_duration=1.0)
        # The blank cur flushes to nothing; only the real word becomes a cue.
        assert [c["text"] for c in cues] == ["realword"]

    def test_split_segment_empty_words_flushes_empty_cur(self):
        # line 159: the final flush() with an empty cur returns immediately.
        assert S._split_segment([], max_chars=10, max_duration=5.0) == []

    def test_stack_bilingual_skips_non_int_index(self):
        # lines 328-329: a translation cue whose index is non-numeric is skipped
        # from the by-index map (falls through to positional matching).
        orig = S.new_track([S.make_cue(1, 0.0, 1.0, "Hi")], lang="en")
        trans = {
            "id": "t",
            "lang": "es",
            "name": "ES",
            "format": "srt",
            "kind": "soft",
            "cues": [{"index": None, "start": 0.0, "end": 1.0, "text": "Hola"}],
        }
        out = S.stack_bilingual(orig, trans)
        # index None excluded from by_index -> positional fallback pairs them.
        assert out["cues"][0]["text"] == "Hi\nHola"

    def test_stack_bilingual_positional_fallback(self):
        # line 336: index miss but pos < len(trans_cues) -> positional match.
        orig = S.new_track([S.make_cue(5, 0.0, 1.0, "Hi")], lang="en")
        trans = S.new_track([S.make_cue(9, 0.0, 1.0, "Hola")], lang="es")
        out = S.stack_bilingual(orig, trans)
        assert out["cues"][0]["text"] == "Hi\nHola"

    def test_parse_timestamp_without_fraction(self):
        # line 410: a timestamp with no fractional part -> frac 0.0.
        assert S.parse_timestamp("01:02:03") == pytest.approx(3723.0)

    def test_read_srt_skips_block_without_arrow(self):
        # line 445: a block whose first non-index line lacks "-->" is skipped.
        raw = "1\nnot a timing line\nbody\n\n2\n00:00:00,000 --> 00:00:01,000\nReal\n"
        cues = S.read_srt(raw)
        assert [c["text"] for c in cues] == ["Real"]

    def test_read_vtt_skips_block_without_arrow(self):
        # line 487: a VTT block (not NOTE) lacking a "-->" line is skipped.
        raw = "WEBVTT\n\njust an id line\nand body, no timing\n\n00:00:00.000 --> 00:00:01.000\nReal\n"
        cues = S.read_vtt(raw)
        assert [c["text"] for c in cues] == ["Real"]

    def test_read_ass_skips_unparseable_dialogue(self):
        # branch 574->562 + lines 598/602-603: a Dialogue line whose timing is
        # garbage (and one with too few fields) -> _parse_dialogue returns None.
        text = (
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,bad,worse,Default,,0,0,0,,nope\n"  # unparseable timestamps
            "Dialogue: 0\n"  # far too few fields
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Good\n"
        )
        cues = S.read_ass(text)
        assert [c["text"] for c in cues] == ["Good"]


# =========================================================================== #
# caption.py
# =========================================================================== #
class TestCaptionGaps:
    def test_wrap_hook_title_balanced_two_line_wrap(self):
        # Exercises the balanced-pack loop (lines 147-157). NOTE: the leftover-
        # append at line 155 (and the 149->157 fall-through) are UNREACHABLE with
        # the ceil-division `per_line` formula -- proven by brute force over all
        # (n, max_lines) -- so they are flagged for a pragma in the report.
        title = "alpha beta gamma delta epsilon zeta eta theta"
        wrapped = cap.wrap_hook_title(title, max_lines=2)
        lines = wrapped.split(r"\N")
        assert len(lines) == 2
        # every original word survives, split across the two balanced lines.
        assert set(title.split()) == set(" ".join(lines).split())


# =========================================================================== #
# caption_remotion.py
# =========================================================================== #
class TestCaptionRemotionGaps:
    def test_ensure_chrome_extracted_bad_zip_returns_none(self, tmp_path):
        # lines 237-238: a corrupt zip -> BadZipFile caught -> None.
        bad = tmp_path / cr.CHROME_HEADLESS_SHELL_ZIP_DEST
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"this is not a zip file")
        assert cr.ensure_chrome_extracted(bad, tmp_path / "extract") is None

    def test_resolve_chromium_settings_hit(self, tmp_path):
        # line 365: SETTING_CHROME points at a real file -> returned directly.
        exe = tmp_path / "chs.exe"
        exe.write_bytes(b"x")
        result = cr.resolve_chromium(
            {cr.SETTING_CHROME: str(exe)},
            env={},
            assets_root=tmp_path / "empty",
        )
        assert result == str(exe)

    def test_run_render_handles_no_stdout_no_stderr(self):
        # branches 545->559 (stderr is None/not iterable) and 561->575 (stdout
        # None): a popen returning a proc with no pipes still completes.
        class _NoPipesProc:
            stdout = None
            stderr = None

            def wait(self, timeout=None):
                return 0

        code, ok_path, tail = cr.run_render(["exe", "r.js", "j.json"], popen=lambda *a, **k: _NoPipesProc())
        assert code == 0
        assert ok_path is None
        assert tail == []

    def test_run_render_drain_skips_blank_and_swallows_iter_error(self):
        # branch 551->549 (a blank stderr line is skipped) and lines 553-554
        # (the stderr iterator raises mid-drain -> caught, never propagates).
        class _BlankThenRaise:
            def __iter__(self):
                yield "\n"  # blank after strip -> `if seg` False (551->549)
                yield "kept line\n"  # appended to the tail
                raise RuntimeError("pipe exploded")  # 553-554: swallowed

        class _Stdout:
            def __iter__(self):
                return iter([])

        class _Proc:
            def __init__(self):
                self.stdout = _Stdout()
                self.stderr = _BlankThenRaise()

            def wait(self, timeout=None):
                return 1

        # The drain thread is joined inside run_render, so the raise is fully
        # contained; the call returns normally with the kept (non-blank) line.
        code, ok_path, tail = cr.run_render(["exe", "r.js", "j.json"], popen=lambda *a, **k: _Proc())
        assert code == 1
        assert "kept line" in tail
        assert "" not in tail  # the blank line was skipped, not appended

    def test_terminate_handles_terminate_and_wait_failures(self):
        # lines 591-592 + 595-599: terminate() raising, then wait() raising ->
        # kill(); and kill() raising too (swallowed).
        class _ProcAllFail:
            def terminate(self):
                raise OSError("cannot terminate")

            def wait(self, timeout=None):
                raise OSError("cannot wait")

            def kill(self):
                raise OSError("cannot kill")

        # Must not raise even though every step fails.
        cr._terminate(_ProcAllFail())

        # A proc whose wait() lingers (raises) but kill() works.
        killed = {"n": 0}

        class _ProcKillRecovers:
            def terminate(self):
                pass

            def wait(self, timeout=None):
                raise OSError("lingering")

            def kill(self):
                killed["n"] += 1

        cr._terminate(_ProcKillRecovers())
        assert killed["n"] == 1

    def test_engine_render_non_transient_failure_breaks_loop(self, tmp_path):
        # branch 698->725: a non-transient failure on the FIRST (and only)
        # attempt falls straight through to the terminal raise without retry.
        electron = tmp_path / "app" / "node_modules" / "electron" / "dist" / f"electron{cr._EXE}"
        electron.parent.mkdir(parents=True)
        electron.write_bytes(b"x")
        render_js = tmp_path / "app" / "render-cli" / "dist" / "render.js"
        render_js.parent.mkdir(parents=True)
        render_js.write_text("//", encoding="utf-8")
        bundle = tmp_path / "app" / "render-cli" / "out" / "remotion-bundle"
        bundle.mkdir(parents=True)

        class _Lines:
            def __init__(self, lines):
                self._lines = lines

            def __iter__(self):
                yield from self._lines

        calls = {"n": 0}

        class _Proc:
            def __init__(self):
                self.stdout = _Lines([])
                self.stderr = _Lines(["RENDER_FAIL composition not found\n"])

            def wait(self, timeout=None):
                return 1

        def popen(argv, **kwargs):
            calls["n"] += 1
            return _Proc()

        engine = cr.RemotionCaptionEngine(
            settings={},
            popen=popen,
            env={},
            dev_root=tmp_path,
            assets_root=tmp_path / "no-assets",
        )
        with pytest.raises(cr.RemotionCaptionError, match="composition not found"):
            engine.render("c.mp4", [], "o.mp4")
        assert calls["n"] == 1  # no retry for a non-transient failure


# =========================================================================== #
# timeline.py
# =========================================================================== #
class TestTimelineGaps:
    def test_default_peaks_dir_uses_config_root(self, monkeypatch):
        # line 76: default_peaks_dir appends "peaks" to the config dir.
        monkeypatch.setattr(tl, "default_config_dir", lambda: Path("/cfg/root"))
        assert tl.default_peaks_dir() == Path("/cfg/root") / "peaks"

    def test_non_dict_cache_payload_is_rebuilt(self, tmp_path):
        # line 218: a cache file whose JSON is valid but not a dict -> miss.
        peaks_dir = tmp_path / "peaks"
        peaks_dir.mkdir()
        cache_file = tl.peaks_cache_path(peaks_dir, "vid-1")
        cache_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")  # a list, not a dict

        svc = tl.Timeline(resolver=lambda vid: None, peaks_dir=peaks_dir)
        assert svc._read_cache("vid-1", "in.mp4", 123) is None


# =========================================================================== #
# fillers.py
# =========================================================================== #
class TestFillersGaps:
    def test_mark_filler_words_skips_blank_phrase(self):
        # line 163: a word that normalizes to "" yields an empty phrase that is
        # skipped (the `if not phrase: continue` guard), then the word is kept.
        words = [
            {"text": "...", "start": 0.0, "end": 0.3},  # normalizes to ""
            {"text": "keep", "start": 0.4, "end": 0.9},
        ]
        drop = fl._mark_filler_words(words, frozenset({"um"}), frozenset())
        assert drop == [False, False]

    def test_keep_sliver_between_two_cuts_is_absorbed(self):
        # lines 252-255: TWO non-adjacent drop spans (separated by a tiny kept
        # word) where the keep-sliver gap (< merge_gap) is absorbed into the
        # previous kept removal span.
        words = [
            fl_w("content", 0.0, 0.5),
            fl_w("um", 0.6, 0.95),  # cut 1 (>= 120ms)
            fl_w("x", 0.96, 0.99),  # tiny kept word: a sub-gap sliver
            fl_w("uh", 1.0, 1.4),  # cut 2 (>= 120ms), only ~50ms after cut 1 ends
            fl_w("end", 1.5, 2.0),
        ]
        keeps, stats = fl.build_cutlist_with_stats(words, "en")
        # The 'x' sliver is absorbed -> the two cuts merge into one removed span.
        assert keeps == [(0.0, 0.6), (1.4, 2.0)]
        assert stats["fillersRemoved"] == 2

    def test_cursor_reaches_window_end_without_trailing_keep(self):
        # branch 269->272 false: a filler at the very END of the window leaves
        # cursor == win_end, so no trailing keep is appended.
        words = [
            fl_w("hello", 0.0, 0.5),
            fl_w("world", 0.6, 1.0),
            fl_w("um", 1.5, 2.0),  # always filler at the window edge
        ]
        keeps = fl.build_cutlist(words, "en")
        # The trailing 'um' is cut; cursor lands exactly on win_end (2.0).
        assert keeps == [(0.0, 1.5)]
        assert all(end <= 2.0 for _, end in keeps)

    def test_absorb_swallows_only_content_keep_degenerate(self):
        # line 275: two fillers bound a tiny content word whose keep-sliver is
        # absorbed (lines 252-255), so the loop produces NO keeps even though not
        # every word is a filler -> the final degenerate guard keeps the window
        # whole. (Re-derived via fresh-context-verify: this path IS reachable,
        # contrary to a first-pass "unreachable" reading of line 234's guard.)
        words = [
            fl_w("um", 0.0, 0.3),  # cut 1 (>= 120ms), at the window start
            fl_w("real", 0.31, 0.33),  # tiny content word between the two cuts
            fl_w("uh", 0.34, 0.7),  # cut 2 (>= 120ms), ~40ms after cut 1 ends
        ]
        keeps, stats = fl.build_cutlist_with_stats(words, "en", window=(0.0, 0.7))
        # The content keep is absorbed -> keeps empty -> degenerate window-whole.
        assert keeps == [(0.0, 0.7)]
        assert stats == {"fillersRemoved": 0, "fillerSeconds": 0.0}


def fl_w(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}
