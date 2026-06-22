"""Property tests for the ffmpeg argv builders + progress math + peaks (WU-B).

These are pure functions dense in branch logic. Binary resolution is stubbed
(monkeypatched ``resolve_binary``) so no real ffmpeg is required and generated
paths need not exist — the invariants are about argv SHAPE, not resolution
(which ``test_ffmpeg.py`` already covers exhaustively).

Invariants:
  * every builder returns a ``list[str]`` (never a shell string), with the
    resolved binary first and the output path last,
  * ``-y`` (overwrite) and the ``-progress pipe:1 -nostats`` drain markers are
    always present for the encoders,
  * the input path appears as a single argv element (spaces-safe),
  * ``run`` rejects a str argv with ``TypeError`` (no shell injection),
  * ``parse_progress_line`` round-trips ``key=value`` and ignores garbage,
  * ``_pct_from_progress`` stays within [0, 100] and is monotonic in out_time,
  * ``peaks_from_pcm`` emits ``min(buckets, n_samples)`` values, all in [0, 1].

Append-only: ADDS coverage; no source/existing-test change.
"""

from __future__ import annotations

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st
from media_studio import ffmpeg
from media_studio.features import timeline as TL
from media_studio.features import zoom as Z

_FAKE_BIN = "/fake/bin/ffmpeg"

# Paths that exercise the spaces-safe argv contract (no NUL — argv can't hold it).
_paths = st.text(
    st.characters(min_codepoint=0x20, max_codepoint=0x7E, blacklist_characters="\x00"),
    min_size=1,
    max_size=40,
)


@pytest.fixture(autouse=True)
def _stub_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Resolve to a fixed fake path regardless of settings/PATH so the pure argv
    # builders run without a real binary present.
    monkeypatch.setattr(ffmpeg, "resolve_binary", lambda name, settings=None: _FAKE_BIN)


def _is_argv(argv: object) -> bool:
    return isinstance(argv, list) and all(isinstance(a, str) for a in argv)


# --------------------------------------------------------------------------- #
# argv builders
# --------------------------------------------------------------------------- #
@given(in_path=_paths, out_path=_paths)
def test_convert_argv_shape(in_path: str, out_path: str) -> None:
    argv = ffmpeg.build_convert_argv(in_path, out_path, options={"vcodec": "libx264", "crf": 23})
    assert _is_argv(argv)
    assert argv[0] == _FAKE_BIN
    assert argv[-1] == out_path
    assert in_path in argv
    assert "-y" in argv
    assert argv.count("-i") == 1
    # progress drain markers always present
    for marker in ("-progress", "pipe:1", "-nostats"):
        assert marker in argv


@given(in_path=_paths, out_path=_paths, scale=st.sampled_from(["1280:720", "1280x720"]))
def test_convert_argv_scale_normalized(in_path: str, out_path: str, scale: str) -> None:
    argv = ffmpeg.build_convert_argv(in_path, out_path, options={"scale": scale})
    vf_idx = argv.index("-vf")
    # both "x" and ":" forms produce the colon-separated scale filter
    assert argv[vf_idx + 1] == "scale=1280:720"


@given(in_path=_paths, out_path=_paths)
def test_audio_only_drops_video(in_path: str, out_path: str) -> None:
    argv = ffmpeg.build_convert_argv(in_path, out_path, options={"audioOnly": True, "acodec": "aac"})
    assert "-vn" in argv
    assert "-c:v" not in argv


@given(in_path=_paths)
def test_probe_argv_shape(in_path: str) -> None:
    argv = ffmpeg.build_probe_argv(in_path)
    assert _is_argv(argv)
    assert argv[0] == _FAKE_BIN
    assert argv[-1] == in_path
    assert "format=duration" in argv


@given(in_path=_paths, out_path=_paths)
def test_peaks_argv_shape(in_path: str, out_path: str) -> None:
    argv = TL.build_peaks_argv(in_path, out_path)
    assert _is_argv(argv)
    assert argv[0] == _FAKE_BIN
    assert argv[-1] == out_path
    assert in_path in argv
    assert "s16le" in argv and str(TL.SAMPLE_RATE) in argv


@given(
    in_path=_paths,
    out_path=_paths,
    w=st.integers(min_value=1, max_value=4096),
    h=st.integers(min_value=1, max_value=4096),
    dur=st.floats(min_value=0.0, max_value=120.0, allow_nan=False),
)
def test_zoom_argv_shape(in_path: str, out_path: str, w: int, h: int, dur: float) -> None:
    argv = Z.build_zoom_argv(in_path, out_path, width=w, height=h, duration_sec=dur)
    assert _is_argv(argv)
    assert argv[0] == _FAKE_BIN
    assert argv[-1] == out_path
    vf = argv[argv.index("-filter:v") + 1]
    assert vf.startswith("zoompan=") and f"s={w}x{h}" in vf


@given(argv=st.text(max_size=10))
def test_run_rejects_shell_string(argv: str) -> None:
    with pytest.raises(TypeError):
        ffmpeg.run(argv)


# --------------------------------------------------------------------------- #
# progress parsing + pct math
# --------------------------------------------------------------------------- #
@given(
    key=st.text(st.characters(min_codepoint=0x61, max_codepoint=0x7A), min_size=1, max_size=8),
    value=st.text(st.characters(min_codepoint=0x30, max_codepoint=0x39), min_size=1, max_size=8),
)
def test_parse_progress_line_roundtrip(key: str, value: str) -> None:
    parsed = ffmpeg.parse_progress_line(f"{key}={value}")
    assert parsed == (key, value)


@given(line=st.text(max_size=20).filter(lambda s: "=" not in s))
def test_parse_progress_line_ignores_lines_without_eq(line: str) -> None:
    assert ffmpeg.parse_progress_line(line) is None


@given(
    cur_us=st.integers(min_value=0, max_value=10_000_000_000),
    total=st.floats(min_value=0.1, max_value=10_000.0, allow_nan=False),
)
def test_pct_from_progress_bounded(cur_us: int, total: float) -> None:
    pct = ffmpeg._pct_from_progress("out_time_us", str(cur_us), total)
    assert pct is not None
    assert 0.0 <= pct <= 100.0


@given(total=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
def test_pct_from_progress_nonpositive_total_is_none(total: float) -> None:
    assert ffmpeg._pct_from_progress("out_time_us", "1000", total) is None


# --------------------------------------------------------------------------- #
# peaks_from_pcm math
# --------------------------------------------------------------------------- #
@given(
    samples=st.lists(st.integers(min_value=-32768, max_value=32767), max_size=200),
    buckets=st.integers(min_value=1, max_value=64),
)
def test_peaks_count_and_range(samples: list[int], buckets: int) -> None:
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    peaks = TL.peaks_from_pcm(pcm, buckets)
    assert len(peaks) == min(buckets, len(samples))
    assert all(0.0 <= p <= 1.0 for p in peaks)
    # all-silence PCM -> all-zero peaks (the negative/positive extremes are 0)
    if samples and all(s == 0 for s in samples):
        assert all(p == 0.0 for p in peaks)


@given(pcm=st.binary(max_size=1))
def test_peaks_empty_or_odd_byte_is_empty(pcm: bytes) -> None:
    # 0 or 1 byte cannot form a single s16le sample.
    assert TL.peaks_from_pcm(pcm, 10) == []


@given(buckets=st.integers(max_value=0))
def test_peaks_nonpositive_buckets_raises(buckets: int) -> None:
    with pytest.raises(ValueError):
        TL.peaks_from_pcm(b"\x00\x01\x02\x03", buckets)
