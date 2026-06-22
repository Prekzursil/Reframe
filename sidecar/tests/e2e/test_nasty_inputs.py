"""E2E NASTY-INPUT regression suite for the real media_studio pipeline.

WU-A part 3 (sidecar leg). Every test here feeds the REAL stack a deliberately
hostile input and asserts the pipeline degrades *gracefully*: it produces a
valid output, OR returns a clear/typed error — but NEVER crashes, hangs, or
emits a malformed/unplayable artifact while claiming success.

These run against the REAL handlers (the same ``protocol.METHODS`` the shipped
sidecar dispatches), REAL ffmpeg/ffprobe, and the REAL subtitle parsers. The
ONLY thing not exercised is the LLM/whisper model stack (no candidate
generation / transcription model) — irrelevant to input-robustness, which is
about the media + parse + export edges.

OPT-IN: tagged ``e2e`` so the default 100%-coverage gate (addopts
``-m 'not e2e'``) DESELECTS this whole module. The graceful-handling code paths
these inputs exercise are already covered by the default unit suite; this module
proves the END-TO-END behavior on hostile inputs, not coverage.

Nasty inputs covered (task WU-A): zero-length media, audio-only, no-speech,
broken/odd codec, weird aspect ratios, malformed SRT/VTT, unicode/RTL captions,
huge timeline.

Run: ``python -m pytest -m e2e sidecar/tests/e2e/test_nasty_inputs.py -v``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio import library as _library
from media_studio.features import subtitles as S
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (_FFMPEG and _FFPROBE),
        reason="ffmpeg/ffprobe required for the nasty-input real-media flows",
    ),
]


# --------------------------------------------------------------------------- #
# in-process JSON-RPC drive (the REAL parse -> dispatch -> handler path)
# --------------------------------------------------------------------------- #
class Rpc:
    """Drive the real registered handlers + a real JobRegistry, like production."""

    def __init__(self, svc: Services) -> None:
        self.svc = svc
        self.events: list[Any] = []
        self.jobs = JobRegistry(
            emit_progress=lambda jid, pct, msg: self.events.append(("progress", jid, pct, msg)),
            emit_done=lambda jid, result: self.events.append(("done", jid, result)),
        )
        self.ctx = RpcContext(emit_notification=lambda obj: None, jobs=self.jobs)

    def _handler(self, method: str) -> Any:
        fn = protocol.METHODS.get(method)
        assert fn is not None, f"method not registered: {method}"
        return fn

    def call(self, method: str, params: dict[str, Any]) -> Any:
        return self._handler(method)(params, self.ctx)

    def run_job(self, method: str, params: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
        out = self.call(method, params)
        assert isinstance(out, dict) and "jobId" in out, f"{method} did not return a jobId: {out!r}"
        self.jobs.join(timeout=timeout)
        done = [e for e in self.events if e[0] == "done" and e[1] == out["jobId"]]
        assert done, f"{method} job {out['jobId']} never completed: {self.events!r}"
        return done[-1][2]


def _new_rpc(tmp_path: Path) -> Rpc:
    """A fresh Services with the real handlers registered (production wiring)."""
    svc = Services(data_dir=tmp_path / "data")
    protocol.clear_methods()
    handlers.register_all(services=svc)
    return Rpc(svc)


# --------------------------------------------------------------------------- #
# real-media fixture builders (real ffmpeg)
# --------------------------------------------------------------------------- #
def _ffmpeg(args: list[str], path: Path) -> bool:
    res = subprocess.run([_FFMPEG, "-y", "-loglevel", "error", *args, str(path)], capture_output=True, text=True)
    return res.returncode == 0 and path.exists() and path.stat().st_size > 0


def _ffprobe_streams(path: str) -> dict[str, Any]:
    res = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    codecs = {s.get("codec_type"): s.get("codec_name") for s in data.get("streams", [])}
    return {
        "video": "video" in codecs,
        "audio": "audio" in codecs,
        "duration": float(data.get("format", {}).get("duration", 0.0) or 0.0),
    }


def _add(rpc: Rpc, media: Path) -> str:
    """Add via the REAL library + REAL ffprobe-backed duration probe."""
    rpc.svc.library = _library.Library(rpc.svc.data_dir / "library.json")
    return rpc.svc.library.add(str(media))["id"]


# --------------------------------------------------------------------------- #
# 1. zero-length media — added, but honestly reported unplayable (no crash)
# --------------------------------------------------------------------------- #
def test_zero_length_media_is_added_but_reported_unplayable(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / "zero.mp4"
    media.write_bytes(b"")  # genuinely empty

    vid = _add(rpc, media)
    verdict = rpc.call("media.playable", {"videoId": vid})
    assert verdict["playable"] is False
    assert verdict.get("reason"), "an unplayable zero-byte file must carry a clear reason"


# --------------------------------------------------------------------------- #
# 2. broken / garbage bytes with a video extension — clear unplayable, no crash
# --------------------------------------------------------------------------- #
def test_broken_codec_garbage_bytes_reported_unplayable(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / "broken.mp4"
    media.write_bytes(b"\x00\x01NOT-A-VALID-CONTAINER\xff\xfe" * 64)

    vid = _add(rpc, media)
    verdict = rpc.call("media.playable", {"videoId": vid})
    assert verdict["playable"] is False
    assert verdict.get("reason")


# --------------------------------------------------------------------------- #
# 3. odd / uncommon codec (mjpeg in AVI) — added & probed, honest non-Chromium
# --------------------------------------------------------------------------- #
def test_odd_codec_mjpeg_is_handled_with_clear_verdict(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / "odd.avi"
    assert _ffmpeg(
        ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2", "-c:v", "mjpeg", "-q:v", "3"],
        media,
    )
    vid = _add(rpc, media)
    verdict = rpc.call("media.playable", {"videoId": vid})
    # mjpeg is a real, decodable stream but not a Chromium-playable codec: the
    # resolver must say so clearly rather than crash or claim playable.
    assert verdict["playable"] is False
    assert "mjpeg" in (verdict.get("reason") or "").lower()


# --------------------------------------------------------------------------- #
# 4. audio-only media — added, probed, no video stream tolerated gracefully
# --------------------------------------------------------------------------- #
def test_audio_only_media_is_handled(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / "audio.m4a"
    assert _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac"], media)

    vid = _add(rpc, media)
    # A bare media.playable on audio-only must return a bool verdict, not throw.
    verdict = rpc.call("media.playable", {"videoId": vid})
    assert isinstance(verdict["playable"], bool)


# --------------------------------------------------------------------------- #
# 5. nonexistent path — a clear, typed RPC-level error, never a stack crash
# --------------------------------------------------------------------------- #
def test_missing_media_yields_clear_error_not_crash(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    rpc.svc.library = _library.Library(rpc.svc.data_dir / "library.json")
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - asserting message below
        rpc.call("media.playable", {"videoId": "does-not-exist"})
    assert "unknown video" in str(excinfo.value).lower()


# --------------------------------------------------------------------------- #
# 6. weird aspect ratios — extreme tall + extreme wide both probe cleanly
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "size"),
    [("tall", "80x720"), ("wide", "1920x40"), ("square", "240x240")],
)
def test_weird_aspect_ratios_probe_and_resolve(tmp_path: Path, name: str, size: str) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / f"{name}.mp4"
    assert _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=24:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ],
        media,
    )
    vid = _add(rpc, media)
    verdict = rpc.call("media.playable", {"videoId": vid})
    # An H.264 stream of any aspect is Chromium-playable; the point is it does not
    # crash on a degenerate 80x720 / 1920x40 frame.
    assert verdict["playable"] is True


# --------------------------------------------------------------------------- #
# 7. no-speech audio export — real CUT->REFRAME->CAPTION->EXPORT on a clip that
#    carries no transcript/speech still produces a VALID playable mp4.
# --------------------------------------------------------------------------- #
def test_no_speech_export_still_produces_valid_mp4(tmp_path: Path) -> None:
    rpc = _new_rpc(tmp_path)
    media = tmp_path / "nospeech.mp4"
    assert _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=24:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ],
        media,
    )
    vid = _add(rpc, media)
    candidate = {
        "rank": 1,
        "start": 1.0,
        "end": 4.0,
        "sourceStart": 1.0,
        "durationSec": 3.0,
        "hook": "no-speech short",
        "why": "nasty-input regression",
        "score": 100,
    }
    done = rpc.run_job(
        "shortmaker.export",
        {
            "videoId": vid,
            "candidates": [candidate],
            "reframeEngine": "claudeshorts",  # in-sidecar CPU crop (no WSL nesting)
            "captionStyle": "libass",  # node-free caption path
        },
    )
    clips = done.get("clips") or []
    assert clips, f"export produced no clips on a no-speech input: {done!r}"
    out_path = clips[0].get("path")
    assert out_path and Path(out_path).exists()
    probe = _ffprobe_streams(out_path)
    assert probe["video"] and probe["duration"] > 0


# --------------------------------------------------------------------------- #
# 8. malformed SRT / VTT — tolerant parsers drop junk blocks, never crash, and
#    surface a CLEAR typed error on a genuinely unparseable timestamp.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reader", ["read_srt", "read_vtt"])
@pytest.mark.parametrize(
    ("name", "text", "expected_cues"),
    [
        ("empty", "", 0),
        ("whitespace_only", "   \n\n   \n", 0),
        ("no_timing_line", "1\njust text, no arrow\n", 0),
        ("missing_index", "00:00:01,000 --> 00:00:02,000\nno index line\n", 1),
        ("trailing_junk", "1\n00:00:01,000 --> 00:00:02,000\nok\n\n\n\ngarbage-no-arrow\n", 1),
    ],
)
def test_malformed_subtitle_blocks_are_dropped_not_crashed(
    reader: str, name: str, text: str, expected_cues: int
) -> None:
    cues = getattr(S, reader)(text)
    assert len(cues) == expected_cues, f"{reader}/{name}: got {cues!r}"


@pytest.mark.parametrize("reader", ["read_srt", "read_vtt"])
def test_unparseable_timestamp_raises_clear_error(reader: str) -> None:
    bad = "1\n00:zz:00 --> 00:00:05\nbad timestamp\n"
    with pytest.raises(ValueError, match="unparseable timestamp"):
        getattr(S, reader)(bad)


# --------------------------------------------------------------------------- #
# 9. unicode / RTL captions — preserved through parse + round-trip; ASS export
#    neutralizes override-block injection (CONTRACTS.md §4).
# --------------------------------------------------------------------------- #
def test_unicode_and_rtl_captions_survive_roundtrip() -> None:
    # Arabic (RTL), CJK, emoji, combining diacritics.
    samples = ["مرحبا بالعالم", "你好，世界", "emoji 🎬🚀 test", "café déjà vu"]
    srt_blocks = [f"{i}\n00:00:0{i},000 --> 00:00:0{i + 1},000\n{txt}\n" for i, txt in enumerate(samples, start=1)]
    parsed = S.read_srt("\n".join(srt_blocks))
    assert [c["text"] for c in parsed] == samples
    # round-trip back out and back in: text must be byte-for-byte preserved.
    reparsed = S.read_srt(S.to_srt(parsed))
    assert [c["text"] for c in reparsed] == samples
    # VTT round-trip too.
    revtt = S.read_vtt(S.to_vtt(parsed))
    assert [c["text"] for c in revtt] == samples


def test_caption_override_injection_is_neutralized_in_ass() -> None:
    evil = S.make_cue(1, 0.0, 1.0, "{\\an8\\pos(0,0)}injected override")
    ass = S.to_ass([evil])
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    # CONTRACTS.md §4: the override-block delimiters must be neutralized, so the
    # cue text can never open an ASS override block ({...}). Without the braces
    # the residual "\an8\pos(0,0)" is inert literal text, not an override.
    assert "{" not in dialogue and "}" not in dialogue
    assert "injected override" in dialogue  # the visible text is still rendered


# --------------------------------------------------------------------------- #
# 10. huge timeline — a very large cue list parses + reindexes without blowing
#     up (no quadratic explosion / recursion crash on size).
# --------------------------------------------------------------------------- #
def test_huge_subtitle_timeline_parses_and_reindexes() -> None:
    n = 20_000
    blocks = [
        f"{i}\n00:{(i // 60) % 60:02d}:{i % 60:02d},000 --> 00:{(i // 60) % 60:02d}:{i % 60:02d},500\nline {i}\n"
        for i in range(1, n + 1)
    ]
    cues = S.read_srt("\n".join(blocks))
    assert len(cues) == n
    # reindex is 1-based, contiguous, and immutable on a huge list.
    reindexed = S.reindex(cues)
    assert reindexed[0]["index"] == 1
    assert reindexed[-1]["index"] == n
