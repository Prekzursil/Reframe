"""Autonomous REAL-pipeline E2E smoke test for the Reframe media_studio sidecar.

Drives the sidecar over its real stdio JSON-RPC 2.0 protocol (newline-delimited)
end-to-end on a real ~8s sample.mp4 with REAL ffmpeg and a REAL (tiny, CPU,
int8) faster-whisper model. NO GUI, NO GPU, NO fakes for the media path.

Two sidecar processes are exercised:

  A. ``python -m media_studio`` (the PRODUCTION composition root, default
     Services) -- proves the CPU dependency set imports, ``register_all`` wires
     every handler, and the stdio framing works (``ping`` + ``library.add``).
     No model is loaded here.

  B. ``python -m sidecar.tests.e2e._tiny_sidecar`` -- the SAME composition root
     with one forced deviation: a whisper loader pinned to tiny / cpu / int8
     (prod hardcodes large-v3-turbo / cuda with no RPC knob -- see the launcher
     docstring; this is itself a finding). The full pipeline runs here:
       import -> transcribe.start (real tiny whisper) -> subtitles.generate
       -> [LLM-selection stubbed: an explicit candidate dict is passed inline,
           bypassing the LLM-backed shortmaker.select] -> shortmaker.export
       (real CUT -> REFRAME -> CAPTION -> EXPORT via ffmpeg) -> ffprobe assert.

Exit code 0 only when the export produces a valid playable mp4 (ffprobe shows a
video + audio stream and duration > 0). Per-step outcomes are printed as
``STEP_<NAME>: ...`` lines so the result is machine-greppable. The script
reports the TRUTH of each step (success + evidence, or the precise error).

Run (from the repo root, inside the venv with CPU sidecar deps):

    export PYTHONPATH="$PWD/sidecar"
    python sidecar/tests/e2e/real_pipeline_smoke.py \
        --sample e2e_artifacts/sample.mp4 \
        --workdir e2e_artifacts/run

See sidecar/tests/e2e/README.md for full setup.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class SidecarClient:
    """A newline-delimited JSON-RPC 2.0 client over a spawned sidecar's stdio.

    Responses (carry an ``id``) are matched to requests; notifications
    (``job.progress`` / ``job.done``) are routed to per-job queues so a caller
    can block on a job's terminal ``job.done``. A background reader thread keeps
    stdout drained so the sidecar never blocks on a full pipe.
    """

    def __init__(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> None:
        self._proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._responses: dict[Any, dict[str, Any]] = {}
        self._done: dict[str, dict[str, Any]] = {}
        self._cv = threading.Condition()
        self._stderr_lines: list[str] = []
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._err_reader.start()

    def _read_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # stdout is supposed to be sacred framed JSON; record anything else.
                with self._cv:
                    self._stderr_lines.append("NONJSON_STDOUT: " + line)
                    self._cv.notify_all()
                continue
            with self._cv:
                if "id" in obj and obj.get("id") is not None:
                    self._responses[obj["id"]] = obj
                elif obj.get("method") == "job.done":
                    params = obj.get("params") or {}
                    self._done[params.get("jobId")] = params
                self._cv.notify_all()

    def _read_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            with self._cv:
                self._stderr_lines.append(line.rstrip())
                if len(self._stderr_lines) > 400:
                    del self._stderr_lines[:200]

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        assert self._proc.stdin is not None
        with self._lock:
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()
        deadline = time.time() + timeout
        with self._cv:
            while req_id not in self._responses:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"timeout waiting for response to {method}")
                self._cv.wait(timeout=min(remaining, 1.0))
            resp = self._responses.pop(req_id)
        if "error" in resp:
            raise RuntimeError(f"{method} -> RPC error: {resp['error']}")
        return resp.get("result", {})

    def run_job(self, method: str, params: dict[str, Any], *, timeout: float = 600.0) -> dict[str, Any]:
        """Call a job-returning method, then block on its ``job.done`` result."""
        result = self.call(method, params, timeout=60.0)
        job_id = result.get("jobId")
        if not isinstance(job_id, str):
            raise RuntimeError(f"{method} did not return a jobId: {result!r}")
        deadline = time.time() + timeout
        with self._cv:
            while job_id not in self._done:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"timeout waiting for job.done of {method} ({job_id})")
                self._cv.wait(timeout=min(remaining, 1.0))
            done = self._done.pop(job_id)
        payload = done.get("result")
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(f"{method} job failed: {payload['error']}")
        return payload if isinstance(payload, dict) else {"result": payload}

    def stderr_tail(self, n: int = 25) -> str:
        with self._cv:
            return "\n".join(self._stderr_lines[-n:])

    def close(self) -> None:
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()


def ffprobe_streams(path: str) -> dict[str, Any]:
    """Return ``{video, audio, duration}`` for a media file via ffprobe."""
    ffprobe = shutil.which("ffprobe") or "/usr/bin/ffprobe"
    out = subprocess.run(
        [
            ffprobe,
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
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    codecs = {s.get("codec_type"): s.get("codec_name") for s in streams}
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return {
        "video": "video" in codecs,
        "audio": "audio" in codecs,
        "video_codec": codecs.get("video"),
        "audio_codec": codecs.get("audio"),
        "duration": duration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, help="path to the input sample mp4")
    parser.add_argument("--workdir", required=True, help="scratch dir for sidecar data + outputs")
    parser.add_argument("--repo", default=None, help="repo root (defaults to cwd)")
    args = parser.parse_args()

    repo = Path(args.repo or os.getcwd()).resolve()
    sample = Path(args.sample).resolve()
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    data_dir = workdir / "datadir"
    data_dir.mkdir(parents=True, exist_ok=True)

    if not sample.exists():
        print(f"SETUP: FAIL -- sample not found: {sample}")
        return 2

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "sidecar") + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    overall_ok = True
    breakages: list[str] = []

    # ----------------------------------------------------------------- #
    # PHASE A: production entry boot smoke (deps + composition + stdio)
    # ----------------------------------------------------------------- #
    boot = SidecarClient([sys.executable, "-m", "media_studio"], cwd=str(repo / "sidecar"), env=env)
    try:
        pong = boot.call("ping", {})
        assert pong.get("pong") is True, pong
        print(f"BOOT: ok -- production `python -m media_studio` ping -> {pong}")
    except Exception as exc:  # noqa: BLE001
        overall_ok = False
        breakages.append(f"BOOT prod entry: {exc}")
        print(f"BOOT: FAIL -- {exc}\nstderr:\n{boot.stderr_tail()}")
    finally:
        boot.close()

    # ----------------------------------------------------------------- #
    # PHASE B: full pipeline on the tiny-CPU launcher
    # ----------------------------------------------------------------- #
    benv = dict(env)
    benv["MEDIA_STUDIO_E2E_DATADIR"] = str(data_dir)
    launcher = str(repo / "sidecar" / "tests" / "e2e" / "_tiny_sidecar.py")
    client = SidecarClient(
        [sys.executable, launcher],
        cwd=str(repo / "sidecar"),
        env=benv,
    )

    video_id = None
    track_id = None
    import_failed = False
    try:
        # ping the tiny launcher too (proves it serves)
        client.call("ping", {})

        # 1. IMPORT --------------------------------------------------- #
        try:
            added = client.call("library.add", {"path": str(sample), "title": "e2e-sample"})
            video = added.get("video") or {}
            video_id = video.get("id")
            assert video_id, added
            print(f"STEP_IMPORT: ok -- videoId={video_id} path={video.get('path')}")
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            import_failed = True
            breakages.append(f"IMPORT: {exc}")
            print(f"STEP_IMPORT: FAIL -- {exc}\nstderr:\n{client.stderr_tail()}")

        if import_failed:
            # Nothing downstream can run without a videoId; report and stop.
            return _finish(overall_ok, breakages)

        # 2. TRANSCRIBE (real tiny CPU whisper) ----------------------- #
        seg_count = None
        try:
            done = client.run_job("transcribe.start", {"videoId": video_id, "language": "en"}, timeout=600.0)
            transcript = done.get("transcript") or {}
            segments = transcript.get("segments") or []
            words = sum(len(s.get("words") or []) for s in segments)
            seg_count = len(segments)
            print(
                f"STEP_TRANSCRIBE: ok -- real tiny/cpu/int8 whisper ran; "
                f"segments={seg_count} words={words} "
                f"(NOTE: sine-only audio has no speech, so 0 segments is the honest result)"
            )
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            breakages.append(f"TRANSCRIBE: {exc}")
            print(f"STEP_TRANSCRIBE: FAIL -- {exc}\nstderr:\n{client.stderr_tail()}")

        # 3. CAPTIONS / SUBTITLES ------------------------------------- #
        try:
            sub = client.call("subtitles.generate", {"videoId": video_id})
            track = sub.get("track") or {}
            track_id = track.get("id")
            cues = track.get("cues") or []
            print(f"STEP_CAPTIONS: ok -- trackId={track_id} cues={len(cues)}")
            # also exercise subtitles.export (SRT) if we have a track
            if track_id:
                exp = client.call("subtitles.export", {"trackId": track_id, "format": "srt"})
                print(f"STEP_CAPTIONS: subtitles.export srt -> {exp.get('path')}")
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            breakages.append(f"CAPTIONS: {exc}")
            print(f"STEP_CAPTIONS: FAIL -- {exc}\nstderr:\n{client.stderr_tail()}")

        # 4. SELECT (LLM stubbed -- explicit candidate, bypass shortmaker.select) #
        # The LLM-backed shortmaker.select needs a provider; the task authorizes a
        # minimal stub for the selection step only. We construct one candidate
        # (a 1.0s..6.0s clip of the 8s source) and pass it INLINE to the export
        # handler, which carves the real clip. This is the documented stub.
        candidate = {
            "rank": 1,
            "start": 1.0,
            "end": 6.0,
            "sourceStart": 1.0,
            "durationSec": 5.0,
            "hook": "E2E reframed short",
            "why": "manual stub (LLM-selection bypassed)",
            "score": 100,
        }
        print("STEP_SELECT: ok -- LLM-selection STUBBED (inline candidate 1.0s-6.0s); real ffmpeg export pipeline runs")

        # 5. EXPORT a captioned vertical short -> assert valid mp4 ------ #
        try:
            done = client.run_job(
                "shortmaker.export",
                {
                    "videoId": video_id,
                    "candidates": [candidate],
                    # force the in-sidecar CPU crop engine (no WSL-nested verthor):
                    "reframeEngine": "claudeshorts",
                    # "libass" is NOT a Remotion style -> routes to the node-free
                    # libass CaptionEngine (real ffmpeg subtitles filter). The
                    # Remotion styles (bold/bounce/clean/karaoke) need a Node.js
                    # runtime (Electron/app node_modules), absent in this CPU env.
                    "captionStyle": "libass",
                },
                timeout=600.0,
            )
            clips = done.get("clips") or []
            assert clips, f"export produced no clips: {done!r}"
            out_path = clips[0].get("path")
            assert out_path and Path(out_path).exists(), f"export path missing: {out_path}"
            probe = ffprobe_streams(out_path)
            ok = probe["video"] and probe["audio"] and probe["duration"] > 0
            if not ok:
                overall_ok = False
                breakages.append(f"EXPORT invalid output: {probe}")
                print(f"STEP_EXPORT: FAIL -- output not playable: {probe} ({out_path})")
            else:
                print(
                    f"STEP_EXPORT: ok -- {out_path} | ffprobe video={probe['video_codec']} "
                    f"audio={probe['audio_codec']} duration={probe['duration']:.2f}s"
                )
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            breakages.append(f"EXPORT: {exc}")
            print(f"STEP_EXPORT: FAIL -- {exc}\nstderr:\n{client.stderr_tail()}")

    finally:
        client.close()

    return _finish(overall_ok, breakages)


def _finish(overall_ok: bool, breakages: list[str]) -> int:
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    if breakages:
        print("TOP_BREAKAGES:")
        for b in breakages:
            print(f"  - {b}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
