#!/usr/bin/env python3
"""Turn a YouTube auto-caption .vtt (rolling/duplicated lines + inline timing tags)
into a clean timestamped transcript: one '[mm:ss] text' line per spoken chunk."""
import re
import sys
from pathlib import Path

SPIKE = Path(__file__).parent
vtt = (SPIKE / "talk.en.vtt").read_text(encoding="utf-8", errors="ignore")


def ts_to_s(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def mmss(s: float) -> str:
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


cue_re = re.compile(r"(\d\d:\d\d:\d\d\.\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d\.\d\d\d)")
out: list[tuple[float, str]] = []
last = ""

for block in re.split(r"\n\n+", vtt):
    m = cue_re.search(block)
    if not m:
        continue
    start = ts_to_s(m.group(1))
    texts = []
    for ln in block.splitlines():
        if "-->" in ln or ln.strip().upper() == "WEBVTT" or ln.startswith(("Kind:", "Language:")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln).strip()  # strip <c>/timing tags
        if ln:
            texts.append(ln)
    text = re.sub(r"\s+", " ", " ".join(texts)).strip()
    if not text or text == last:
        continue
    if last and text in last:  # subset of what we already have
        continue
    if last and text.startswith(last):  # rolling continuation -> replace, keep earlier start
        out[-1] = (out[-1][0], text)
        last = text
        continue
    out.append((start, text))
    last = text

transcript = "\n".join(f"[{mmss(s)}] {t}" for s, t in out)
(SPIKE / "transcript.txt").write_text(transcript, encoding="utf-8")
dur = out[-1][0] / 60 if out else 0
words = sum(len(t.split()) for _, t in out)
print(f"segments={len(out)} duration_min={dur:.1f} words={words}")
print("--- first 3 ---")
for s, t in out[:3]:
    print(f"[{mmss(s)}] {t[:90]}")
print("--- last 2 ---")
for s, t in out[-2:]:
    print(f"[{mmss(s)}] {t[:90]}")
