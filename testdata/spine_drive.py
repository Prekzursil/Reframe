#!/usr/bin/env python3
"""Phase-0 spine driver: stage the never-yet-run pipeline through the app's own RPC.

Each stage spawns a FRESH sidecar (library/projects persist in %APPDATA%; candidates
do NOT, so they're carried in spine_state.json exactly like the UI forwards them).

Usage:  python spine_drive.py add|transcribe|select|export
GPU is managed BETWEEN stages by the orchestrator (whisper/Qwen/verthor don't co-fit on 6GB).
"""
from __future__ import annotations

import collections
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
SIDECAR_DIR = REPO / "sidecar"
PY = SIDECAR_DIR / ".venv" / "Scripts" / "python.exe"
VIDEO = HERE / "sinek-talk.mp4"
STATE = HERE / "spine_state.json"

PROMPT = "Find the 5 most share-worthy 20-60s clips for vertical shorts from this talk."
CONTROLS = {"count": 5, "minSec": 20, "maxSec": 60, "aspect": "9:16", "language": "en"}


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(d: dict) -> None:
    STATE.write_text(json.dumps(d, indent=2), encoding="utf-8")


class Sidecar:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [str(PY), "-m", "media_studio"],
            cwd=str(SIDECAR_DIR),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.next_id = 1
        # CRITICAL: drain stderr continuously. faster-whisper/huggingface write
        # chatty tqdm progress to stderr; an unread PIPE fills (~64KB) and BLOCKS
        # the sidecar entirely (the exact hang seen on the first run).
        self.stderr_tail: collections.deque[str] = collections.deque(maxlen=60)
        self._last_dl_print = 0.0
        t = threading.Thread(target=self._drain_stderr, daemon=True)
        t.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            line = raw.rstrip("\n")
            # tqdm redraws with \r; keep only the last segment.
            seg = line.split("\r")[-1].strip()
            if not seg:
                continue
            self.stderr_tail.append(seg)
            low = seg.lower()
            now = time.time()
            if ("download" in low or "%|" in seg or "fetching" in low or "error" in low
                    or "exception" in low) and now - self._last_dl_print > 5:
                print(f"  [sidecar] {seg[:110]}", flush=True)
                self._last_dl_print = now

    def call(self, method: str, params: dict | None = None, job_timeout: float = 7200.0):
        """Send one request; if the result is a job handle, follow progress to job.done."""
        rid = self.next_id
        self.next_id += 1
        req = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()

        result = None
        deadline = time.time() + job_timeout
        job_id = None
        last_pct = -1
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"sidecar died during {method} (see stderr)")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == rid:
                if "error" in obj:
                    raise RuntimeError(f"{method} -> RPC error: {obj['error']}")
                result = obj["result"]
                if isinstance(result, dict) and set(result) == {"jobId"}:
                    job_id = result["jobId"]
                    print(f"  [{method}] job {job_id} started...", flush=True)
                    continue
                return result
            m = obj.get("method")
            p = obj.get("params", {})
            if m == "job.progress" and p.get("jobId") == job_id:
                pct = p.get("pct", 0)
                if pct != last_pct:
                    print(f"  [{job_id}] {pct}%  {p.get('message','')}", flush=True)
                    last_pct = pct
            elif m == "job.done" and p.get("jobId") == job_id:
                res = p.get("result")
                if isinstance(res, dict) and "error" in res:
                    err = res["error"]
                    raise RuntimeError(f"job failed: {err.get('type')}: {err.get('message')}")
                return res
        raise TimeoutError(f"{method} timed out")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()

    def dump_stderr_tail(self, n: int = 25) -> None:
        for ln in list(self.stderr_tail)[-n:]:
            print(f"  [stderr] {ln}")


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    state = load_state()
    sc = Sidecar()
    try:
        pong = sc.call("ping")
        print(f"ping -> {pong}")

        if stage == "add":
            r = sc.call("library.add", {"path": str(VIDEO)})
            video = r["video"]
            state["videoId"] = video["id"]
            save_state(state)
            print(f"ADDED: id={video['id']} duration={video['durationSec']:.1f}s title={video['title']}")

        elif stage == "transcribe":
            r = sc.call("transcribe.start", {"videoId": state["videoId"]})
            tr = r.get("transcript", r)
            segs = tr.get("segments", [])
            words = sum(len(s.get("words", [])) for s in segs)
            state["transcribed"] = True
            save_state(state)
            print(f"TRANSCRIBED: lang={tr.get('language')} segments={len(segs)} words={words}")
            if segs:
                print(f"  first: [{segs[0]['start']:.1f}s] {segs[0]['text'][:80]}")

        elif stage == "select":
            r = sc.call("shortmaker.select", {
                "videoId": state["videoId"], "prompt": PROMPT, "controls": CONTROLS,
            })
            cands = r.get("candidates", [])
            state["candidates"] = cands
            save_state(state)
            print(f"SELECTED {len(cands)} candidates:")
            for c in cands:
                print(f"  #{c.get('rank')} [{c.get('start'):.0f}-{c.get('end'):.0f}s] "
                      f"({c.get('durationSec'):.0f}s) score={c.get('score')} hook={c.get('hook','')[:60]}")

        elif stage == "export":
            cands = state["candidates"]
            ids = [f"{c['rank']}@{c['sourceStart']}" for c in cands]
            r = sc.call("shortmaker.export", {
                "videoId": state["videoId"], "candidateIds": ids, "candidates": cands,
            })
            clips = r.get("clips", [])
            print(f"EXPORTED {len(clips)} clips:")
            for cl in clips:
                p = Path(cl.get("path", ""))
                size = p.stat().st_size if p.exists() else 0
                print(f"  {p}  ({size/1e6:.1f} MB, exists={p.exists()})")
        else:
            print("usage: spine_drive.py add|transcribe|select|export")
            return 2
        return 0
    except Exception as exc:
        print(f"STAGE FAILED: {exc}")
        sc.dump_stderr_tail()
        return 1
    finally:
        sc.close()


if __name__ == "__main__":
    raise SystemExit(main())
