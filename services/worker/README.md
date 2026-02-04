# Reframe Worker

Celery worker skeleton using Redis for broker/result.

## Quick start

```
BROKER_URL=redis://redis:6379/0 \
RESULT_BACKEND=redis://redis:6379/0 \
celery -A worker.celery_app worker --loglevel=info
```

Tasks available:
- `tasks.ping`
- `tasks.echo`

## Captions: speaker labels (optional)

The captions worker supports **optional speaker labels** via diarization.

Job options (POST `/api/v1/captions/jobs`):

- `speaker_labels`: boolean (default `false`)
- `diarization_backend`: `"noop"` or `"pyannote"` (default `"noop"`)
- `diarization_model`: default `"pyannote/speaker-diarization-3.1"`
- `min_segment_duration`: float seconds (default `0.0`)

Notes:
- Diarization is **offline-default** (`noop`). The `"pyannote"` backend is optional and heavy (pulls `torch`).
- If `REFRAME_OFFLINE_MODE=true`, the worker will refuse `"pyannote"` diarization (to avoid network downloads) and continue without speaker labels.
- If required deps aren’t installed, the worker logs a warning and continues without speaker labels (job still completes).

### Enabling pyannote in Docker images

By default, the worker images install `media-core` without extras. To enable pyannote diarization, install the optional extra:

```bash
pip install '/worker/packages/media-core[diarize-pyannote]'
```

If the model requires a Hugging Face token, set one of:

- `HUGGINGFACE_TOKEN`
- `HF_TOKEN`

### Benchmark diarization (CPU/memory)

To measure rough wall time + peak RSS for pyannote diarization on a sample file:

```bash
make tools-ffmpeg
pip install 'packages/media-core[diarize-pyannote]'
HF_TOKEN=... scripts/benchmark_diarization.py /path/to/video-or-audio.mp4 --warmup --runs 1
```

Notes:
- This is expected to be **heavy** (Torch + model downloads). Run it on the target machine you plan to deploy on.
- `REFRAME_OFFLINE_MODE=true` is intended to disable network-backed providers; for pyannote benchmarks you’ll need network access for model download.
- `scripts/benchmark_diarization.py` will also pick up `HF_TOKEN` / `HUGGINGFACE_TOKEN` from the repo `.env` if present.

## Captions: high-quality transcription (Whisper Large v3)

For best offline/free quality, prefer **Whisper Large v3** via the `faster_whisper` backend.

In the web UI:
- Backend: `faster_whisper`
- Model: `whisper-large-v3` (alias; maps to `large-v3` internally)

To pre-download the model into the worker’s cache (recommended so the first job doesn’t stall on downloads):

```bash
docker compose -f infra/docker-compose.yml run --rm worker python /worker/scripts/prefetch_whisper_model.py --model whisper-large-v3
```

## Translate subtitles: Groq (optional)

By default, `tasks.translate_subtitles` uses **Argos Translate** (offline) when available, and falls back to **NoOp** when not.

You can opt into **Groq** (OpenAI-compatible chat API) by setting `GROQ_API_KEY` and either:
- passing `translator_backend: "groq"` in the job `options`, or
- letting the worker auto-fallback to Groq when Argos isn’t installed.

Env vars:
- `GROQ_API_KEY` (required)
- `GROQ_MODEL` (optional, default: `llama3-8b-8192`)
- `GROQ_BASE_URL` (optional, default: `https://api.groq.com/openai/v1`)
- `GROQ_TIMEOUT_SECONDS` (optional, default: `30`)

Notes:
- If `REFRAME_OFFLINE_MODE=true`, the worker will refuse Groq and fall back to offline/noop behavior.

### Install Argos language packs (offline translation)

Argos requires per-language-pair packages. To install one in the worker container:

```bash
docker compose -f infra/docker-compose.yml run --rm worker python /worker/scripts/install_argos_pack.py --list
docker compose -f infra/docker-compose.yml run --rm worker python /worker/scripts/install_argos_pack.py --src en --tgt es
```
