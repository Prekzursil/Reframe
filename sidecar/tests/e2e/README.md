# Real-pipeline E2E smoke test (CPU, no GUI, no GPU)

`real_pipeline_smoke.py` drives the `media_studio` sidecar over its real stdio
JSON-RPC 2.0 protocol and runs the full short-making pipeline on a real sample
video with **real ffmpeg** and a **real (tiny, CPU, int8) faster-whisper model**.
No GUI, no GPU, no fakes for the media path.

## What it exercises

Two sidecar processes:

1. **`python -m media_studio`** (the production composition root, default
   `Services`) — proves the CPU dependency set imports, `register_all` wires
   every handler, and the stdio framing works (`ping`). No model is loaded here.

2. **`_tiny_sidecar.py`** — the SAME composition root with one forced deviation:
   a whisper loader pinned to **tiny / cpu / int8**. The full flow runs here:

   `library.add` → `transcribe.start` (real tiny whisper) → `subtitles.generate`
   + `subtitles.export` (SRT) → *[LLM-selection stubbed: an explicit candidate is
   passed inline to bypass the LLM-backed `shortmaker.select`]* →
   `shortmaker.export` (real CUT → REFRAME → CAPTION → EXPORT via ffmpeg) →
   `ffprobe` assert (video + audio + duration > 0).

Each step prints a `STEP_<NAME>: ok|FAIL ...` line. Exit code is 0 only when the
export produces a valid playable mp4.

## Why a separate tiny launcher exists (a real finding)

`media_studio.features.transcribe.transcribe_with_engine` calls `transcribe_file(...)`
**without** forwarding `model`/`device`/`compute_type`; those are default-arg-bound
to `large-v3-turbo` / `cuda` / `float16`. There is **no RPC or settings knob** to
choose the model size — the only seam is `Services(whisper_loader=...)`. So the
production `python -m media_studio` on a CPU/no-GPU box attempts the ~1.5 GB
large-v3-turbo download and a CUDA load (then falls back to CPU). `_tiny_sidecar.py`
injects a tiny-forcing loader so the E2E stays fast and on the tiny model. This is
the single intentional deviation from the production entry; everything else is the
real pipeline.

## Setup (WSL / Linux, CPU)

```bash
python3.12 -m venv .venv-e2e
. .venv-e2e/bin/activate
pip install --upgrade pip wheel setuptools
# CPU runtime deps (from sidecar/runtime_setup/requirements-sidecar.txt,
# MINUS the GPU nvidia-* wheels, kokoro-onnx, and torch/chatterbox):
pip install \
  faster-whisper==1.2.1 ctranslate2==4.8.0 scenedetect==0.7 \
  opencv-python-headless==4.13.0.92 httpx==0.28.1 numpy==2.4.6 av==17.1.0 \
  onnxruntime==1.26.0 huggingface_hub==1.19.0 tokenizers==0.23.1

# Generate a real ~8s sample (real video + real audio):
mkdir -p e2e_artifacts
ffmpeg -y -f lavfi -i testsrc=size=640x360:rate=30:duration=8 \
       -f lavfi -i sine=frequency=440:duration=8 \
       -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest e2e_artifacts/sample.mp4
```

Requires `ffmpeg` + `ffprobe` on `PATH` (e.g. `/usr/bin/ffmpeg` 6.1.1, built
`--enable-libass`).

## Run

```bash
export PYTHONPATH="$PWD/sidecar"
python sidecar/tests/e2e/real_pipeline_smoke.py \
    --sample e2e_artifacts/sample.mp4 \
    --workdir e2e_artifacts/run \
    --repo "$PWD"
```

## Notes / known constraints

- **No speech in the sine sample** → real tiny whisper returns 0 segments. That is
  the honest result; the script reports it explicitly rather than claiming words.
  To exercise word-level captions, substitute a sample that contains real speech.
- **Caption engine:** the script forces `captionStyle: "libass"` (the node-free
  ffmpeg `subtitles`/`ass` path). The Remotion styles (`bold`/`bounce`/`clean`/
  `karaoke`) require a Node.js runtime (Electron / `app/node_modules`) absent in a
  headless CPU env — selecting one fails with `RemotionCaptionError: node runner
  not found`.
- **Reframe engine:** forced to `claudeshorts` (the in-sidecar OpenCV crop). The
  default `auto`/`verthor` engine shells out to `wsl bash <script>`, which is not
  available when the sidecar already runs inside WSL; `claudeshorts` degrades
  mediapipe → haar → center-crop, so center-crop runs with cv2 only.
- **Job store:** the launcher uses the in-memory job store (`rpc.main()` with no
  store) on purpose — `DiskJobStore.write()` has a concurrency race (a fixed
  `<job>.json.tmp` name; the dispatch and worker threads race on the same temp →
  `FileNotFoundError`). The media pipeline is unaffected by store choice (the
  transcript persists via the project manifest, not the job store).
