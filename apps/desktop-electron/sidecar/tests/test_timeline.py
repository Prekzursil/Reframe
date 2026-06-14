"""Tests for features/timeline.py (P2 T1: timeline.peaks).

Everything heavy is mocked at the documented seams: the ffmpeg decode is a
recording fake (``run`` seam) that writes synthesized PCM to the argv's output
path, and binaries resolve from a tmp dir of stub ffmpeg/ffprobe files. No
subprocess is ever spawned.
"""
from __future__ import annotations

import json
import os
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from media_studio import protocol
from media_studio.protocol import RpcContext, RpcError
from media_studio.features import timeline as tl


# --------------------------------------------------------------------------- #
# fixtures + helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    """A fake ffmpeg install dir (both plain + .exe for cross-OS resolution)."""
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
        (d / name).write_text("", encoding="utf-8")
    return d


@pytest.fixture()
def settings(bin_dir: Path) -> Dict[str, Any]:
    return {"ffmpegPath": str(bin_dir)}


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """A fake source video file (content is irrelevant — run() is faked)."""
    src = tmp_path / "videos" / "talk one.mp4"  # space: argv-list safety
    src.parent.mkdir()
    src.write_bytes(b"\x00" * 64)
    return src


def pcm_bytes(samples: List[int]) -> bytes:
    """Pack int16 samples as little-endian s16le PCM."""
    return struct.pack(f"<{len(samples)}h", *samples)


class FakeRun:
    """Records argv calls and writes ``pcm`` to the argv's output path."""

    def __init__(self, pcm: bytes, code: int = 0) -> None:
        self.pcm = pcm
        self.code = code
        self.calls: List[List[str]] = []

    def __call__(self, argv: List[str], total_sec: float = 0.0, **kwargs: Any) -> int:
        assert isinstance(argv, list)  # argv lists only (A6 lesson 4)
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(self.pcm)
        return self.code


def make_service(
    source: Path,
    settings: Dict[str, Any],
    tmp_path: Path,
    run: Any,
    *,
    video_id: str = "vid-1",
    buckets: int = tl.TARGET_BUCKETS,
) -> tl.Timeline:
    def resolver(vid: str) -> Optional[str]:
        return str(source) if vid == video_id else None

    return tl.Timeline(
        resolver=resolver,
        settings_provider=lambda: settings,
        peaks_dir=tmp_path / "peaks",
        run=run,
        buckets=buckets,
    )


@pytest.fixture()
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# peaks_from_pcm: the downsample math (the DONE-WHEN core)
# --------------------------------------------------------------------------- #
class TestPeaksFromPcm:
    def test_empty_pcm_yields_empty(self):
        assert tl.peaks_from_pcm(b"") == []

    def test_single_odd_byte_is_ignored(self):
        assert tl.peaks_from_pcm(b"\x7f") == []

    def test_trailing_odd_byte_is_ignored(self):
        # Two full samples + one stray byte -> two buckets, stray dropped.
        data = pcm_bytes([16384, -16384]) + b"\x7f"
        peaks = tl.peaks_from_pcm(data, buckets=10)
        assert peaks == [16384 / 32768.0, 16384 / 32768.0]

    def test_fewer_samples_than_buckets_is_one_bucket_per_sample(self):
        peaks = tl.peaks_from_pcm(pcm_bytes([0, 32767, -32768]), buckets=2000)
        assert len(peaks) == 3
        assert peaks[0] == 0.0
        assert peaks[1] == pytest.approx(32767 / 32768.0)
        assert peaks[2] == 1.0  # |-32768|/32768 clamps to exactly 1.0

    def test_negative_extreme_dominates_bucket(self):
        # Bucket peak must be max(|x|), not max(x).
        peaks = tl.peaks_from_pcm(pcm_bytes([100, -30000]), buckets=1)
        assert peaks == [30000 / 32768.0]

    def test_exact_bucket_division(self):
        # 4 samples / 2 buckets -> [max(|0|,|8192|), max(|-16384|,|4096|)].
        peaks = tl.peaks_from_pcm(pcm_bytes([0, 8192, -16384, 4096]), buckets=2)
        assert peaks == [8192 / 32768.0, 16384 / 32768.0]

    def test_uneven_bucket_boundaries_cover_every_sample(self):
        # 10 samples / 4 buckets -> boundaries 0..2,2..5,5..7,7..10 (sizes
        # 2,3,2,3). The loud sample in each span must land in that bucket.
        samples = [0] * 10
        samples[1] = 1000   # bucket 0  (0..2)
        samples[4] = -2000  # bucket 1  (2..5)
        samples[5] = 3000   # bucket 2  (5..7)
        samples[9] = 4000   # bucket 3  (7..10)
        peaks = tl.peaks_from_pcm(pcm_bytes(samples), buckets=4)
        assert peaks == [
            1000 / 32768.0,
            2000 / 32768.0,
            3000 / 32768.0,
            4000 / 32768.0,
        ]

    def test_large_input_downsamples_to_target_buckets(self):
        samples = [(i % 2000) - 1000 for i in range(50_000)]
        peaks = tl.peaks_from_pcm(pcm_bytes(samples), buckets=2000)
        assert len(peaks) == 2000
        assert all(0.0 <= p <= 1.0 for p in peaks)

    def test_all_values_normalized_into_unit_range(self):
        peaks = tl.peaks_from_pcm(pcm_bytes([-32768, 32767, 0, -1]), buckets=4)
        assert all(0.0 <= p <= 1.0 for p in peaks)

    def test_invalid_bucket_count_raises(self):
        with pytest.raises(ValueError):
            tl.peaks_from_pcm(pcm_bytes([1]), buckets=0)


# --------------------------------------------------------------------------- #
# argv builder
# --------------------------------------------------------------------------- #
class TestBuildPeaksArgv:
    def test_argv_shape(self, settings: Dict[str, Any]):
        argv = tl.build_peaks_argv("C:/v/talk one.mp4", "C:/t/out.pcm", settings)
        assert isinstance(argv, list)
        assert argv[0].lower().startswith(str(Path(settings["ffmpegPath"])).lower())
        # decode recipe: mono, 8 kHz, raw s16le, first audio stream only
        for pair in (
            ["-i", "C:/v/talk one.mp4"],
            ["-map", "0:a:0"],
            ["-ac", "1"],
            ["-ar", str(tl.SAMPLE_RATE)],
            ["-f", "s16le"],
            ["-progress", "pipe:1"],
        ):
            i = argv.index(pair[0])
            assert argv[i + 1] == pair[1]
        assert argv[-1] == "C:/t/out.pcm"
        assert "-nostdin" in argv and "-nostats" in argv and "-vn" in argv

    def test_path_with_spaces_survives_as_single_element(self, settings):
        argv = tl.build_peaks_argv("C:/my videos/a b.mp4", "C:/t/o.pcm", settings)
        assert "C:/my videos/a b.mp4" in argv  # one argv element, not shell-split


# --------------------------------------------------------------------------- #
# cache path
# --------------------------------------------------------------------------- #
class TestCachePath:
    def test_cache_path_is_videoid_json(self, tmp_path: Path):
        assert tl.peaks_cache_path(tmp_path, "vid-1") == tmp_path / "vid-1.json"

    def test_video_id_is_sanitized(self, tmp_path: Path):
        p = tl.peaks_cache_path(tmp_path, "../evil/..\\id")
        assert p.parent == tmp_path
        assert "/" not in p.name and "\\" not in p.name and ".." not in p.stem

    def test_empty_id_falls_back(self, tmp_path: Path):
        assert tl.peaks_cache_path(tmp_path, "///").name == "video.json"


# --------------------------------------------------------------------------- #
# the service: decode, cache hit, invalidation
# --------------------------------------------------------------------------- #
class TestTimelinePeaks:
    def test_first_call_decodes_and_returns_shape(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([0, 16384, -32768, 8192]))
        svc = make_service(source, settings, tmp_path, run)
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        assert result["sampleRate"] == tl.SAMPLE_RATE
        assert result["peaks"] == [
            0.0,
            16384 / 32768.0,
            1.0,
            8192 / 32768.0,
        ]
        assert len(run.calls) == 1
        assert str(source) in run.calls[0]  # source path as ONE argv element

    def test_cache_file_written_with_invalidation_keys(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([100]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)
        cache_file = tl.peaks_cache_path(tmp_path / "peaks", "vid-1")
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["sourcePath"] == str(source)
        assert data["sourceMtimeNs"] == os.stat(source).st_mtime_ns
        assert data["sampleRate"] == tl.SAMPLE_RATE
        assert data["peaks"] == [100 / 32768.0]

    def test_cache_hit_skips_ffmpeg_and_is_fast(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        # Build the cache once, then re-ask with a runner that MUST not fire.
        seed = FakeRun(pcm_bytes(list(range(-1000, 1000))))
        make_service(source, settings, tmp_path, seed).peaks({"videoId": "vid-1"}, ctx)

        def explode(*a: Any, **kw: Any) -> int:
            raise AssertionError("cache hit must not invoke ffmpeg")

        svc = make_service(source, settings, tmp_path, explode)
        t0 = time.perf_counter()
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        elapsed = time.perf_counter() - t0
        assert result["peaks"]  # served from cache
        assert result["sampleRate"] == tl.SAMPLE_RATE
        # DONE-WHEN: peaks for a cached file answer well under 5 s (this is a
        # single small-JSON read; the bound is generous to absorb CI jitter).
        assert elapsed < 5.0

    def test_cache_hit_returns_identical_payload(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([5, -7, 9]))
        svc = make_service(source, settings, tmp_path, run)
        first = svc.peaks({"videoId": "vid-1"}, ctx)
        second = svc.peaks({"videoId": "vid-1"}, ctx)
        assert second == first
        assert len(run.calls) == 1  # one decode total

    def test_source_mtime_change_invalidates_cache(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([111]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)
        assert len(run.calls) == 1

        # Touch the source to a different mtime -> rebuild on next ask.
        st = os.stat(source)
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        run.pcm = pcm_bytes([222])
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        assert len(run.calls) == 2
        assert result["peaks"] == [222 / 32768.0]

    def test_source_path_change_invalidates_cache(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([50]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)

        # Same videoId now resolves to a DIFFERENT file (moved/re-added).
        moved = source.with_name("moved.mp4")
        moved.write_bytes(source.read_bytes())
        st = os.stat(source)
        os.utime(moved, ns=(st.st_atime_ns, st.st_mtime_ns))  # same mtime!
        svc2 = make_service(moved, settings, tmp_path, run)
        svc2.peaks({"videoId": "vid-1"}, ctx)
        assert len(run.calls) == 2  # path mismatch forced a rebuild

    def test_corrupt_cache_is_rebuilt(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([42]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)
        cache_file = tl.peaks_cache_path(tmp_path / "peaks", "vid-1")
        cache_file.write_text("{not json", encoding="utf-8")
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        assert len(run.calls) == 2
        assert result["peaks"] == [42 / 32768.0]

    def test_malformed_cache_payload_is_rebuilt(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([42]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)
        cache_file = tl.peaks_cache_path(tmp_path / "peaks", "vid-1")
        good = json.loads(cache_file.read_text(encoding="utf-8"))
        good["peaks"] = "not-a-list"
        cache_file.write_text(json.dumps(good), encoding="utf-8")
        svc.peaks({"videoId": "vid-1"}, ctx)
        assert len(run.calls) == 2

    def test_temp_pcm_file_is_cleaned_up(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes([1, 2, 3]))
        svc = make_service(source, settings, tmp_path, run)
        svc.peaks({"videoId": "vid-1"}, ctx)
        leftovers = list((tmp_path / "peaks").glob("*.pcm"))
        assert leftovers == []

    def test_custom_bucket_count_is_honored(
        self, source: Path, settings, tmp_path: Path, ctx: RpcContext
    ):
        run = FakeRun(pcm_bytes(list(range(100))))
        svc = make_service(source, settings, tmp_path, run, buckets=10)
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        assert len(result["peaks"]) == 10


# --------------------------------------------------------------------------- #
# error paths (direct-return method -> structured RpcError)
# --------------------------------------------------------------------------- #
class TestErrors:
    def test_missing_video_id_param(self, source, settings, tmp_path, ctx):
        svc = make_service(source, settings, tmp_path, FakeRun(b""))
        with pytest.raises(RpcError) as exc_info:
            svc.peaks({}, ctx)
        assert exc_info.value.code == protocol.ErrorCode.INVALID_PARAMS

    def test_unknown_video_id(self, source, settings, tmp_path, ctx):
        svc = make_service(source, settings, tmp_path, FakeRun(b""))
        with pytest.raises(RpcError) as exc_info:
            svc.peaks({"videoId": "nope"}, ctx)
        assert exc_info.value.code == protocol.ErrorCode.INVALID_PARAMS
        assert "nope" in exc_info.value.message

    def test_missing_source_file(self, settings, tmp_path: Path, ctx):
        gone = tmp_path / "gone.mp4"
        svc = make_service(gone, settings, tmp_path, FakeRun(b""))
        with pytest.raises(RpcError) as exc_info:
            svc.peaks({"videoId": "vid-1"}, ctx)
        assert exc_info.value.code == protocol.ErrorCode.INVALID_PARAMS

    def test_ffmpeg_failure_surfaces_as_internal_error(
        self, source, settings, tmp_path, ctx
    ):
        run = FakeRun(b"", code=1)
        svc = make_service(source, settings, tmp_path, run)
        with pytest.raises(RpcError) as exc_info:
            svc.peaks({"videoId": "vid-1"}, ctx)
        assert exc_info.value.code == protocol.ErrorCode.INTERNAL_ERROR
        assert "ffmpeg" in exc_info.value.message

    def test_ffmpeg_failure_writes_no_cache(self, source, settings, tmp_path, ctx):
        svc = make_service(source, settings, tmp_path, FakeRun(b"", code=2))
        with pytest.raises(RpcError):
            svc.peaks({"videoId": "vid-1"}, ctx)
        assert not tl.peaks_cache_path(tmp_path / "peaks", "vid-1").exists()

    def test_settings_provider_crash_does_not_break_decode(
        self, source, tmp_path, ctx, bin_dir, monkeypatch
    ):
        # A crashing settings provider falls back to {} (then env override).
        monkeypatch.setenv("MEDIA_STUDIO_FFMPEG", str(bin_dir / "ffmpeg.exe"))
        run = FakeRun(pcm_bytes([3]))

        def boom() -> Dict[str, Any]:
            raise RuntimeError("settings store on fire")

        svc = tl.Timeline(
            resolver=lambda vid: str(source),
            settings_provider=boom,
            peaks_dir=tmp_path / "peaks",
            run=run,
        )
        result = svc.peaks({"videoId": "vid-1"}, ctx)
        assert result["peaks"] == [3 / 32768.0]


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_installs_timeline_peaks(self, source, settings, tmp_path):
        registered: Dict[str, Any] = {}
        service = tl.register(
            resolver=lambda vid: str(source),
            settings_provider=lambda: settings,
            peaks_dir=tmp_path / "peaks",
            run=FakeRun(pcm_bytes([1])),
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert set(registered) == {"timeline.peaks"}
        assert registered["timeline.peaks"] == service.peaks

    def test_register_defaults_to_protocol_register(self, source, tmp_path):
        # conftest's _restore_methods snapshots/restores protocol.METHODS.
        tl.register(
            resolver=lambda vid: str(source),
            peaks_dir=tmp_path / "peaks",
            run=FakeRun(b""),
        )
        assert "timeline.peaks" in protocol.METHODS

    def test_duplicate_registration_fails_loudly(self, source, tmp_path):
        kwargs: Dict[str, Any] = dict(
            resolver=lambda vid: str(source),
            peaks_dir=tmp_path / "peaks",
            run=FakeRun(b""),
        )
        tl.register(**kwargs)
        with pytest.raises(ValueError):
            tl.register(**kwargs)
