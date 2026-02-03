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
