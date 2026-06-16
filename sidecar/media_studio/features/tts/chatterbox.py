"""Chatterbox TTS engine — voice-clone via an ISOLATED env (CONTRACTS.md A4, T2).

Chatterbox (resemble-ai) needs torch — which is BANNED from the main sidecar
env (A6 lesson 5). So this engine never imports it: synthesis is a
**subprocess seam** into a separately-installed environment:

    <env_python> -m chatterbox_runner <job.json>

* the runner script (:mod:`.chatterbox_runner`, shipped in this package) is
  made importable in that process via ``PYTHONPATH`` — it executes IN the
  isolated env and does the heavy imports there;
* the env itself is a U4 manifest **env-asset** (``installer="env"``) with a
  PINNED requirements list (chatterbox-tts + torch CUDA12 wheels) registered
  below; ``assets.ensure(["chatterbox-env"])`` materializes it under
  ``%APPDATA%/media-studio/envs/chatterbox`` via pip ``--target`` (A7);
* every subprocess pipe is DRAINED (``subprocess.run`` -> communicate
  internally — A6 lesson 2) and the call is an argv LIST (lesson 4).

CONTRACT-NOTE (CUDA12 wheels): the manifest validator requires ``pkg==ver``
pins; the ``+cu124`` local-version pins below satisfy that, but pip can only
resolve them with the PyTorch index available — the env install step needs
``PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124`` in the
process environment (the assets manager inherits ``os.environ``). See
WIRING-T2.md for where the wiring agent sets it.

CONTRACT-NOTE (voice): for a voice-clone engine the A4 ``voice`` parameter is
the REFERENCE SAMPLE's wav path (``tts.dub.start``'s ``sampleId`` resolves to
it) — there is no named-voice catalog; stored samples surface as this
engine's voices (see :mod:`.voices`).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ...assets.manifest import AssetEntry, register_asset
from ...settings_store import default_config_dir
from ...util import get_logger
from .engine import Cue, TtsEngine, TtsError, Voice

log = get_logger("media_studio.tts.chatterbox")

# --------------------------------------------------------------------------- #
# U4 manifest env-asset (PINNED — A6 lesson 5)
# --------------------------------------------------------------------------- #
CHATTERBOX_ENV_ASSET = "chatterbox-env"
CHATTERBOX_ENV_DEST = "envs/chatterbox"
CHATTERBOX_ENV_SIZE_MB = 6500
# PINNED requirements (manifest rejects loose specifiers). torch/torchaudio
# carry the cu124 local version — CUDA 12 wheels off download.pytorch.org
# (PIP_EXTRA_INDEX_URL needed at install time; see module docstring).
CHATTERBOX_REQUIREMENTS: tuple[str, ...] = (
    "chatterbox-tts==0.1.2",
    "torch==2.6.0+cu124",
    "torchaudio==2.6.0+cu124",
)
#: the index pip needs for the +cu124 wheels (wiring sets it; kept here so
#: the value is pinned next to the requirements it serves).
TORCH_EXTRA_INDEX_URL = "https://download.pytorch.org/whl/cu124"


def _register_assets() -> None:
    register_asset(
        AssetEntry(
            name=CHATTERBOX_ENV_ASSET,
            kind="env",
            size_mb=CHATTERBOX_ENV_SIZE_MB,
            dest=CHATTERBOX_ENV_DEST,
            label="Chatterbox voice-clone env (torch CUDA12, isolated)",
            installer="env",
            requirements=CHATTERBOX_REQUIREMENTS,
        )
    )


_register_assets()

# Subprocess runner seam: (argv, extra_env) -> (returncode, combined output).
RunCmd = Callable[[Sequence[str], dict[str, str] | None], tuple[int, str]]


def _default_run_cmd(argv: Sequence[str], extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run the runner subprocess with argv LISTS and fully-drained pipes.

    Mirrors the assets manager's drained-runner pattern: ``subprocess.run``
    drains stdout/stderr continuously via ``communicate()`` so a chatty torch
    load can never fill a pipe and freeze the sidecar (A6 lesson 2; the
    proven 29-min Popen-PIPE freeze). stderr merges into stdout so the
    failure tail lands in one place for the error payload.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(  # noqa: S603 - argv list, shell never
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout or ""


# --------------------------------------------------------------------------- #
# pure builders (unit-tested without any subprocess)
# --------------------------------------------------------------------------- #
def default_env_dir(root: str | None = None) -> str:
    """The chatterbox env's install dir under the assets root (A7 layout)."""
    base = Path(root) if root is not None else default_config_dir()
    return str(base / CHATTERBOX_ENV_DEST)


def runner_dir() -> str:
    """The directory holding :mod:`.chatterbox_runner` (this package)."""
    return str(Path(__file__).resolve().parent)


def build_synth_argv(python_exe: str, job_path: str) -> list[str]:
    """argv for one synthesis job: ``<env_python> -m chatterbox_runner <job.json>``."""
    return [str(python_exe), "-m", "chatterbox_runner", str(job_path)]


def runner_extra_env(env_dir: str) -> dict[str, str]:
    """Env vars that point the subprocess at the ISOLATED env + the runner.

    ``PYTHONPATH`` = the pip ``--target`` env dir (torch et al.) + this
    package's dir (so ``-m chatterbox_runner`` resolves). The env dir comes
    FIRST so the isolated packages win over anything ambient.
    """
    return {"PYTHONPATH": os.pathsep.join([str(env_dir), runner_dir()])}


def build_job_payload(
    cues: Sequence[Cue],
    sample_path: str,
    lang: str,
    out_wav: str,
    rate: float,
) -> dict[str, Any]:
    """The JSON job document the runner consumes (pure; schema is ours)."""
    return {
        "cues": [
            {
                "start": float(c.get("start", 0.0)),
                "end": float(c.get("end", 0.0)),
                "text": str(c.get("text", "")),
            }
            for c in cues
        ],
        "samplePath": str(sample_path),
        "lang": str(lang or ""),
        "outWav": str(out_wav),
        "rate": float(rate),
    }


class ChatterboxEngine(TtsEngine):
    """A4 voice-clone engine: chatterbox-tts in its own downloaded env."""

    id = "chatterbox"
    label = "Chatterbox (voice clone)"
    online = False
    voice_clone = True

    def __init__(
        self,
        *,
        env_dir: str | None = None,
        python_exe: str | None = None,
        run_cmd: RunCmd | None = None,
        assets_root: str | None = None,
    ) -> None:
        self.env_dir = env_dir or default_env_dir(assets_root)
        # A7: the isolated env is pip --target packages run by the HOST
        # python with PYTHONPATH pointing in — there is no second python.exe.
        self.python_exe = python_exe or sys.executable
        self._run_cmd: RunCmd = run_cmd or _default_run_cmd

    def voices(self) -> list[Voice]:
        # Voice-clone: the catalog is the user's stored samples; the voices
        # module surfaces them as engine="chatterbox" rows. Nothing static here.
        return []

    # -- A4 surface ------------------------------------------------------------
    def synth(
        self,
        cues: Sequence[Cue],
        voice: str,
        lang: str,
        out_wav: str,
        *,
        rate: float = 1.0,
    ) -> str:
        """Clone ``voice`` (a reference-sample wav path) speaking ``cues``.

        Writes the job JSON, spawns the runner inside the isolated env, and
        verifies the output WAV exists. All failures raise :class:`TtsError`
        carrying the subprocess output tail (-> job.done error payload).
        """
        if not cues:
            raise TtsError("chatterbox synth: no cues given")
        if not voice or not Path(voice).is_file():
            raise TtsError(f"chatterbox synth: reference sample not found: {voice!r} (add one via tts.sample.add)")
        if not Path(self.env_dir).is_dir():
            raise TtsError(
                f"chatterbox env missing at {self.env_dir} — install the "
                f"{CHATTERBOX_ENV_ASSET!r} asset first (assets.ensure)"
            )

        out = Path(out_wav)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = build_job_payload(cues, voice, lang, str(out), rate)
        with tempfile.TemporaryDirectory(prefix="ms-chatterbox-") as tmp:
            job_path = Path(tmp) / "job.json"
            job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            argv = build_synth_argv(self.python_exe, str(job_path))
            code, output = self._run_cmd(argv, runner_extra_env(self.env_dir))
        if code != 0:
            tail = "\n".join((output or "").splitlines()[-12:])
            raise TtsError(f"chatterbox runner failed (exit {code}): {tail}")
        if not out.is_file():
            raise TtsError("chatterbox runner exited 0 but produced no wav")
        return str(out)


__all__ = [
    "CHATTERBOX_ENV_ASSET",
    "CHATTERBOX_ENV_DEST",
    "CHATTERBOX_REQUIREMENTS",
    "TORCH_EXTRA_INDEX_URL",
    "ChatterboxEngine",
    "build_job_payload",
    "build_synth_argv",
    "default_env_dir",
    "runner_dir",
    "runner_extra_env",
]
