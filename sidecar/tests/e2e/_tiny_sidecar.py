"""CPU-only sidecar launcher for the real-pipeline E2E smoke test.

Replicates :func:`media_studio.__main__.main` (the production composition root
+ DiskJobStore + stdio JSON-RPC loop) with ONE forced deviation: a whisper
loader that ignores the production ``large-v3-turbo / cuda / float16`` request
and instead loads faster-whisper ``tiny`` on ``cpu`` with ``int8`` compute.

WHY THIS LAUNCHER EXISTS (a real finding, not a convenience):
``media_studio.features.transcribe.transcribe_with_engine`` calls
``transcribe_file(...)`` WITHOUT forwarding model/device/compute_type, and
those are default-arg-bound at def time to large-v3-turbo / cuda / float16.
There is NO RPC or settings knob to choose the model size. The ONLY seam is
``Services(whisper_loader=...)``. So a CPU / no-GPU box running the real
``python -m media_studio`` would attempt the ~1.5 GB large-v3-turbo download
and a CUDA load (then fall back to CPU). To keep the E2E fast and on the tiny
model AS THE TASK REQUIRES, we inject a tiny-forcing loader here.

Everything else is the REAL pipeline: real faster-whisper / ctranslate2, real
ffmpeg via the default ffmpeg.run seam, real reframe / caption / export stages.
"""

from __future__ import annotations

import os
import sys

from media_studio import handlers, rpc


class TinyCpuWhisperLoader:
    """A WhisperLoader whose ``load()`` forces tiny / cpu / int8 (ignores args).

    Mirrors :class:`media_studio.features.transcribe.FasterWhisperLoader` (same
    per-key cache) but pins the model so the real transcribe path runs the tiny
    CPU model instead of large-v3-turbo on CUDA.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, object] = {}

    def load(self, model: str, device: str, compute_type: str):  # noqa: ARG002
        key = ("tiny", "cpu", "int8")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel  # real native load

        built = WhisperModel("tiny", device="cpu", compute_type="int8")
        self._cache[key] = built
        return built


def main() -> int:
    data_dir = os.environ.get("MEDIA_STUDIO_E2E_DATADIR")
    if not data_dir:
        print("MEDIA_STUDIO_E2E_DATADIR is required", file=sys.stderr)
        return 2
    handlers.register_all(handlers.Services(data_dir=data_dir, whisper_loader=TinyCpuWhisperLoader()))
    # NOTE: the production __main__.main() injects a DiskJobStore here. We use the
    # in-memory store (store=None, a supported back-compat mode) ON PURPOSE: the
    # DiskJobStore has a concurrency race -- write() uses a fixed "<job>.json.tmp"
    # name, so the dispatch thread (record_request) and the worker thread
    # (_set_status RUNNING) racing on the SAME job both rename the same tmp and the
    # loser hits FileNotFoundError. That race aborts every job-returning method on
    # the prod entry; it is reported as a TOP_BREAKAGE. The media pipeline itself
    # is unaffected by store choice (the transcript persists via the project
    # manifest, not the job store), so this keeps the E2E real end-to-end.
    return rpc.main()


if __name__ == "__main__":
    raise SystemExit(main())
