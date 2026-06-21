"""Tests for the FROZEN dub-alignment recipe (features/tts/align.py, T2).

Covers the unit's DONE criteria: the clamp math including the exact ±15%
edges, the pad math, the per-cue plan, the argv builder, the timeline concat
plan, and a real stdlib-wave concat round-trip. No heavy import, no real
ffmpeg — the run/duration/resynth seams are injected fakes.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from media_studio import ffmpeg
from media_studio.features.tts import align
from media_studio.features.tts.engine import (
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    write_pcm_wav,
)

SETTINGS = {"ffmpegPath": "C:/tools/ffmpeg/ffmpeg.exe"}


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    """Pin binary resolution so tests never depend on a real ffmpeg install."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")


# --------------------------------------------------------------------------- #
# clamp math — ±15% edges (FROZEN)
# --------------------------------------------------------------------------- #
class TestAtempoFactor:
    def test_exact_ratio_inside_band_passes_through(self):
        assert align.atempo_factor(10.5, 10.0) == pytest.approx(1.05)
        assert align.atempo_factor(9.5, 10.0) == pytest.approx(0.95)

    def test_upper_edge_exactly_1_15(self):
        # actual/target == 1.15 exactly: ON the edge, not clamped past it.
        assert align.atempo_factor(11.5, 10.0) == pytest.approx(align.ATEMPO_MAX)

    def test_lower_edge_exactly_0_85(self):
        assert align.atempo_factor(8.5, 10.0) == pytest.approx(align.ATEMPO_MIN)

    def test_above_band_clamps_to_1_15(self):
        assert align.atempo_factor(20.0, 10.0) == align.ATEMPO_MAX
        assert align.atempo_factor(11.6, 10.0) == align.ATEMPO_MAX

    def test_below_band_clamps_to_0_85(self):
        assert align.atempo_factor(5.0, 10.0) == align.ATEMPO_MIN
        assert align.atempo_factor(8.4, 10.0) == align.ATEMPO_MIN

    def test_degenerate_inputs_yield_identity(self):
        assert align.atempo_factor(0.0, 10.0) == 1.0
        assert align.atempo_factor(10.0, 0.0) == 1.0
        assert align.atempo_factor(-1.0, 10.0) == 1.0


class TestResynthRate:
    def test_ratio_passes_through(self):
        assert align.resynth_rate(12.0, 10.0) == pytest.approx(1.2)

    def test_clamped_to_speaking_range(self):
        assert align.resynth_rate(100.0, 10.0) == align.RESYNTH_RATE_MAX
        assert align.resynth_rate(1.0, 10.0) == align.RESYNTH_RATE_MIN

    def test_degenerate_inputs_yield_identity(self):
        assert align.resynth_rate(0.0, 10.0) == 1.0
        assert align.resynth_rate(10.0, 0.0) == 1.0


class TestNeedsResynth:
    def test_within_threshold_no_ask(self):
        assert not align.needs_resynth(10.1, 10.0)  # 1% off

    def test_beyond_threshold_asks(self):
        assert align.needs_resynth(10.5, 10.0)  # 5% off
        assert align.needs_resynth(9.0, 10.0)

    def test_degenerate_no_ask(self):
        assert not align.needs_resynth(0.0, 10.0)
        assert not align.needs_resynth(10.0, 0.0)


# --------------------------------------------------------------------------- #
# pad math + per-cue plan
# --------------------------------------------------------------------------- #
class TestPadAndPlan:
    def test_pad_fills_remaining_slot(self):
        assert align.pad_seconds(8.0, 10.0) == pytest.approx(2.0)

    def test_no_negative_pad(self):
        assert align.pad_seconds(12.0, 10.0) == 0.0

    def test_target_duration_from_cue(self):
        assert align.target_duration({"start": 2.0, "end": 5.5}) == pytest.approx(3.5)
        assert align.target_duration({"start": 5.0, "end": 4.0}) == 0.0

    def test_plan_short_audio_padded_to_target(self):
        # 8s audio into a 10s slot: factor clamps at 0.85 -> ~9.41s, pad fills.
        plan = align.plan_cue(8.0, 10.0)
        assert plan["atempo"] == align.ATEMPO_MIN
        adjusted = 8.0 / align.ATEMPO_MIN
        assert plan["padSec"] == pytest.approx(10.0 - adjusted)
        assert plan["outSec"] == pytest.approx(10.0)

    def test_plan_long_audio_clamped_overrun_accepted(self):
        # 13s audio into a 10s slot: cap at 1.15 -> ~11.3s, NO pad, overrun kept.
        plan = align.plan_cue(13.0, 10.0)
        assert plan["atempo"] == align.ATEMPO_MAX
        assert plan["padSec"] == 0.0
        assert plan["outSec"] == pytest.approx(13.0 / align.ATEMPO_MAX)
        assert plan["outSec"] > 10.0

    def test_plan_near_match_skips_atempo(self):
        plan = align.plan_cue(9.95, 10.0)  # 0.5% off -> within epsilon
        assert plan["atempo"] == 1.0
        assert plan["padSec"] == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
# argv builder
# --------------------------------------------------------------------------- #
class TestBuildAlignArgv:
    def test_full_chain_shape(self):
        argv = align.build_align_argv(
            "C:/work dir/in.wav",
            "C:/work dir/out.wav",
            atempo=1.1,
            pad_sec=0.5,
            settings=SETTINGS,
        )
        assert isinstance(argv, list)
        assert all(isinstance(a, str) for a in argv)
        af = argv[argv.index("-af") + 1]
        assert "atempo=1.1" in af
        assert "apad=pad_dur=0.5" in af
        # normalization is ALWAYS applied so concat can be a stdlib wave write
        assert argv[argv.index("-ar") + 1] == str(DEFAULT_SAMPLE_RATE)
        assert argv[argv.index("-ac") + 1] == str(DEFAULT_CHANNELS)
        assert argv[argv.index("-c:a") + 1] == "pcm_s16le"
        assert argv[-1] == "C:/work dir/out.wav"
        # paths with spaces survive because argv is a LIST (A6 lesson 4)
        assert "C:/work dir/in.wav" in argv

    def test_identity_factor_and_no_pad_drops_filter(self):
        argv = align.build_align_argv("in.wav", "out.wav", settings=SETTINGS)
        assert "-af" not in argv

    def test_epsilon_factor_skipped(self):
        argv = align.build_align_argv("in.wav", "out.wav", atempo=1.005, pad_sec=0.0, settings=SETTINGS)
        assert "-af" not in argv


# --------------------------------------------------------------------------- #
# per-cue orchestration (seams mocked; recipe ORDER)
# --------------------------------------------------------------------------- #
class TestAlignCueWav:
    def test_resynth_asked_when_off_target(self, tmp_path):
        calls = []

        def fake_duration(path):
            # first take 13s; re-synth take 10.4s. Match on the BASENAME — the
            # pytest tmp dir embeds this test's own name ("...resynth..."), so a
            # full-path substring check would tag raw.wav as the re-synth take.
            from pathlib import Path as _P

            return 10.4 if "resynth" in _P(str(path)).name else 13.0

        def fake_resynth(rate, path):
            calls.append(("resynth", rate, path))
            return path

        def fake_run(argv, **kwargs):
            calls.append(("run", list(argv)))
            return 0

        result = align.align_cue_wav(
            str(tmp_path / "raw.wav"),
            10.0,
            str(tmp_path / "out.wav"),
            resynth=fake_resynth,
            run=fake_run,
            duration=fake_duration,
            settings=SETTINGS,
        )
        kinds = [c[0] for c in calls]
        assert kinds == ["resynth", "run"]  # re-synth BEFORE the atempo pass
        assert calls[0][1] == pytest.approx(align.resynth_rate(13.0, 10.0))
        # residual 10.4/10 = 1.04 within the band -> exact factor used
        assert result["plan"]["atempo"] == pytest.approx(1.04)
        assert result["path"] == str(tmp_path / "out.wav")

    def test_no_resynth_when_close(self, tmp_path):
        asked = []
        result = align.align_cue_wav(
            str(tmp_path / "raw.wav"),
            10.0,
            str(tmp_path / "out.wav"),
            resynth=lambda rate, path: asked.append(rate) or path,
            run=lambda argv, **kw: 0,
            duration=lambda path: 10.1,
            settings=SETTINGS,
        )
        assert asked == []
        assert result["outSec"] == pytest.approx(10.1, abs=0.2)

    def test_failed_resynth_falls_back_to_first_take(self, tmp_path):
        def bad_resynth(rate, path):
            raise RuntimeError("engine refused")

        result = align.align_cue_wav(
            str(tmp_path / "raw.wav"),
            10.0,
            str(tmp_path / "out.wav"),
            resynth=bad_resynth,
            run=lambda argv, **kw: 0,
            duration=lambda path: 13.0,
            settings=SETTINGS,
        )
        assert result["plan"]["atempo"] == align.ATEMPO_MAX

    def test_empty_wav_raises(self, tmp_path):
        with pytest.raises(align.AlignError):
            align.align_cue_wav(
                str(tmp_path / "raw.wav"),
                10.0,
                str(tmp_path / "out.wav"),
                run=lambda argv, **kw: 0,
                duration=lambda path: 0.0,
                settings=SETTINGS,
            )

    def test_ffmpeg_failure_raises(self, tmp_path):
        with pytest.raises(align.AlignError):
            align.align_cue_wav(
                str(tmp_path / "raw.wav"),
                10.0,
                str(tmp_path / "out.wav"),
                run=lambda argv, **kw: 1,
                duration=lambda path: 10.0,
                settings=SETTINGS,
            )

    def test_garbage_resynth_take_falls_back_to_first(self, tmp_path):
        """A re-synth that produces an empty/unreadable wav reverts to take 1."""
        runs = []

        def fake_duration(path):
            from pathlib import Path as _P

            # first take 13s (off-target -> asks re-synth); the re-synth take
            # reads 0 (garbage) so the aligner must fall back to the first take.
            return 0.0 if "resynth" in _P(str(path)).name else 13.0

        def fake_resynth(rate, path):
            # "produce" the file but it reads as 0s above.
            return path

        def fake_run(argv, **kw):
            runs.append(list(argv))
            return 0

        result = align.align_cue_wav(
            str(tmp_path / "raw.wav"),
            10.0,
            str(tmp_path / "out.wav"),
            resynth=fake_resynth,
            run=fake_run,
            duration=fake_duration,
            settings=SETTINGS,
        )
        # fell back to the 13s first take -> clamped at the +15% ceiling
        assert result["plan"]["atempo"] == align.ATEMPO_MAX
        # the aligned ffmpeg pass reads the ORIGINAL raw.wav, not the resynth one
        assert any("raw.wav" in a for a in runs[-1])


# --------------------------------------------------------------------------- #
# timeline concat plan + stdlib wave concat
# --------------------------------------------------------------------------- #
class TestConcatPlan:
    def test_gaps_inserted_at_cue_starts(self):
        cues = [
            {"start": 1.0, "end": 3.0, "text": "a"},
            {"start": 5.0, "end": 7.0, "text": "b"},
        ]
        plan = align.concat_plan(cues, [2.0, 2.0])
        assert plan == [
            {"type": "silence", "sec": pytest.approx(1.0)},
            {"type": "cue", "index": 0},
            {"type": "silence", "sec": pytest.approx(2.0)},
            {"type": "cue", "index": 1},
        ]

    def test_overrun_shifts_timeline_without_negative_gap(self):
        cues = [
            {"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 2.0, "end": 4.0, "text": "b"},
        ]
        # cue 0 overran to 3s (clamped long): cue 1 follows immediately.
        plan = align.concat_plan(cues, [3.0, 2.0])
        assert plan == [
            {"type": "cue", "index": 0},
            {"type": "cue", "index": 1},
        ]

    def test_trailing_silence_to_total(self):
        plan = align.concat_plan([{"start": 0.0, "end": 1.0}], [1.0], total_sec=4.0)
        assert plan[-1] == {"type": "silence", "sec": pytest.approx(3.0)}

    def test_length_mismatch_raises(self):
        with pytest.raises(align.AlignError):
            align.concat_plan([{"start": 0, "end": 1}], [])

    def test_empty_inputs_yield_empty_plan(self):
        assert align.concat_plan([], []) == []


class TestConcatWavs:
    @staticmethod
    def _make_wav(path: Path, seconds: float) -> str:
        frames = b"\x01\x00" * int(seconds * DEFAULT_SAMPLE_RATE)
        return write_pcm_wav(str(path), frames)

    def test_round_trip_durations(self, tmp_path):
        a = self._make_wav(tmp_path / "a.wav", 0.5)
        b = self._make_wav(tmp_path / "b.wav", 0.25)
        cues = [
            {"start": 0.5, "end": 1.0, "text": "a"},
            {"start": 2.0, "end": 2.25, "text": "b"},
        ]
        plan = align.concat_plan(cues, [0.5, 0.25], total_sec=3.0)
        out = align.concat_wavs(plan, [a, b], str(tmp_path / "track.wav"))
        with wave.open(out, "rb") as wf:
            assert wf.getframerate() == DEFAULT_SAMPLE_RATE
            assert wf.getnchannels() == DEFAULT_CHANNELS
            duration = wf.getnframes() / wf.getframerate()
        assert duration == pytest.approx(3.0, abs=0.01)

    def test_mismatched_format_raises(self, tmp_path):
        odd = tmp_path / "odd.wav"
        frames = b"\x01\x00" * 8000
        write_pcm_wav(str(odd), frames, sample_rate=8000)
        plan = [{"type": "cue", "index": 0}]
        with pytest.raises(align.AlignError):
            align.concat_wavs(plan, [str(odd)], str(tmp_path / "out.wav"))

    def test_unknown_cue_index_raises(self, tmp_path):
        with pytest.raises(align.AlignError):
            align.concat_wavs([{"type": "cue", "index": 3}], [], str(tmp_path / "out.wav"))

    def test_zero_length_silence_segment_writes_nothing(self, tmp_path):
        """A silence segment rounding to 0 frames is skipped (branch 301->303)."""
        a = self._make_wav(tmp_path / "a.wav", 0.25)
        # a 0.0s silence segment in front of the cue contributes no frames.
        plan = [{"type": "silence", "sec": 0.0}, {"type": "cue", "index": 0}]
        out = align.concat_wavs(plan, [a], str(tmp_path / "track.wav"))
        with wave.open(out, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        assert duration == pytest.approx(0.25, abs=0.01)

    def test_unreadable_cue_wav_raises(self, tmp_path):
        """A cue path that exists but is not a valid WAV surfaces AlignError."""
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not a wav at all")
        plan = [{"type": "cue", "index": 0}]
        with pytest.raises(align.AlignError, match="unreadable cue wav"):
            align.concat_wavs(plan, [str(bad)], str(tmp_path / "out.wav"))


class TestRemoveQuietly:
    def test_removes_existing_file(self, tmp_path):
        f = tmp_path / "tmp.wav"
        f.write_bytes(b"x")
        align.remove_quietly(str(f))
        assert not f.exists()

    def test_missing_file_does_not_raise(self, tmp_path):
        # best-effort cleanup never raises on a missing path
        align.remove_quietly(str(tmp_path / "never-existed.wav"))
