#!/usr/bin/env python3
"""Spike: prompt->short SELECTION via a local LLM (LM Studio OpenAI-compatible server).
Feeds the timestamped transcript + the P1 short-maker selection prompt, prints ranked clips.
Usage: python select.py ["user prompt"]"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

SPIKE = Path(__file__).parent
transcript = (SPIKE / "transcript.txt").read_text(encoding="utf-8")
BASE = os.environ.get("LLM_BASE", "http://localhost:1234/v1")


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def _post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


model = _get("/models")["data"][0]["id"]
user_prompt = sys.argv[1] if len(sys.argv) > 1 else "Find the 5 most share-worthy clips for vertical short-form."

system = (
    "You are an elite short-form video editor. Think step by step FIRST, then output JSON.\n"
    "THINK: (1) State the talk's single core THESIS in one sentence. (2) List its 6-8 most quotable / "
    "counterintuitive / emotional lines (the transcript may contain '(Applause)' markers - those mark "
    "high-impact moments; weight them). (3) For each, find the COMPLETE thought around it - the setup AND the "
    "payoff - not just one sentence.\n"
    "THEN select the 5 best clips for vertical shorts. HARD RULES: each clip is a self-contained complete "
    "thought; each runs 20-60 SECONDS (end minus start MUST be >= 20 and <= 60 - extend to include the "
    "surrounding setup/payoff, NEVER a 3-second fragment); opens on a hook, ends on a satisfying or curiosity "
    "beat. The single most quotable line of the whole talk MUST be one of the 5. Use the [mm:ss] timestamps. "
    "After thinking, output ONLY the JSON object.")
user = (
    f"{user_prompt}\n\n"
    'Return JSON exactly: {"clips":[{"rank":1,"start":"mm:ss","end":"mm:ss","duration_sec":40,'
    '"hook":"opening words","why":"one-line reason it will perform","score":0-100}]}  '
    "(duration_sec = end minus start in seconds; it MUST be between 20 and 60).\n\n"
    f"Transcript:\n{transcript}")

t0 = time.time()
resp = _post("/chat/completions", {
    "model": model,
    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    "temperature": 0.4, "max_tokens": 6000})
dt = time.time() - t0

content = resp["choices"][0]["message"]["content"]
content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()  # drop Qwen3 reasoning
m = re.search(r"\{.*\}", content, re.S)
try:
    clips = json.loads(m.group(0))["clips"] if m else []
except Exception as e:
    print(f"JSON parse failed ({e}); raw:\n{content[:1200]}")
    sys.exit(1)

usage = resp.get("usage", {})
print(f"model={model}  latency={dt:.1f}s  prompt_tokens={usage.get('prompt_tokens','?')}  clips={len(clips)}\n")
for c in clips:
    print(f"  #{c.get('rank')}  [{c.get('start')}–{c.get('end')}]  score={c.get('score')}")
    print(f"      HOOK: {c.get('hook','')[:90]}")
    print(f"      WHY : {c.get('why','')[:110]}")
(SPIKE / "selection_result.json").write_text(json.dumps(clips, indent=2), encoding="utf-8")
print(f"\nsaved -> {SPIKE / 'selection_result.json'}")
