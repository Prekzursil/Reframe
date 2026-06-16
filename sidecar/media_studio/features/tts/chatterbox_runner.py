"""Chatterbox synthesis runner — executes INSIDE the isolated env (T2).

Invoked by :mod:`.chatterbox` as::

    <env_python> -m chatterbox_runner <job.json>

with ``PYTHONPATH`` pointing at the pip ``--target`` env (torch, chatterbox-tts)
plus this directory. It is NOT part of the sidecar's runtime import graph:
the file lives in the package only so it ships with the app, and the module
is import-light by design — **all heavy imports (torch / chatterbox) happen
inside main()**, never at import time, so pytest collection and the sidecar
process never load them (A6 lessons 1/5).

Job document (written by ``chatterbox.build_job_payload``)::

    {"cues": [{"start","end","text"}], "samplePath": str,
     "lang": str, "outWav": str, "rate": float}

Output: one WAV at ``outWav`` containing the cloned voice speaking every cue
in order. Errors print to stderr and exit non-zero (the engine surfaces the
tail through the job.done error payload).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def parse_job(raw: Any) -> dict[str, Any]:
    """Validate the job document (pure; unit-tested from the sidecar env)."""
    if not isinstance(raw, dict):
        raise ValueError("job must be a JSON object")
    cues = raw.get("cues")
    if not isinstance(cues, list) or not cues:
        raise ValueError("job.cues must be a non-empty array")
    texts: list[str] = []
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("job.cues entries must be objects")
        texts.append(str(cue.get("text", "")))
    sample = raw.get("samplePath")
    if not isinstance(sample, str) or not sample:
        raise ValueError("job.samplePath (str) is required")
    out_wav = raw.get("outWav")
    if not isinstance(out_wav, str) or not out_wav:
        raise ValueError("job.outWav (str) is required")
    rate = raw.get("rate", 1.0)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    return {
        "texts": texts,
        "samplePath": sample,
        "lang": str(raw.get("lang") or ""),
        "outWav": out_wav,
        "rate": rate,
    }


def _synthesize(job: dict[str, Any]) -> None:  # pragma: no cover - isolated env only
    """The heavy path — runs ONLY in the chatterbox env (torch present)."""
    import torch  # noqa: PLC0415 - isolated-env import by design
    import torchaudio  # noqa: PLC0415 - isolated-env import by design
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415 - isolated-env import

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)

    chunks = []
    for text in job["texts"]:
        text = text.strip()
        if not text:
            continue
        wav = model.generate(text, audio_prompt_path=job["samplePath"])
        chunks.append(wav)
    if not chunks:
        raise ValueError("no speakable text in job.cues")
    audio = torch.cat(chunks, dim=-1)
    out = Path(job["outWav"])
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), audio.cpu(), model.sr)


def main(argv: list[str] | None = None) -> int:
    """Entry: read <job.json>, synthesize, exit 0 on success."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m chatterbox_runner <job.json>", file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        job = parse_job(raw)
    except (OSError, ValueError) as exc:
        print(f"chatterbox_runner: bad job file: {exc}", file=sys.stderr)
        return 2
    try:
        _synthesize(job)
    except Exception as exc:  # noqa: BLE001 - report any failure on stderr
        print(f"chatterbox_runner: synthesis failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry
    raise SystemExit(main())
