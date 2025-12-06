import logging
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlmodel import Session, create_engine

# Ensure app package is importable for shared models/config when running from services/.
ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "apps" / "api"
if str(API_PATH) not in sys.path:
    sys.path.append(str(API_PATH))

from app.config import get_settings
from app.models import Job, JobStatus, MediaAsset
from celery import Celery

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery("reframe_worker", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.task_default_queue = "default"

logger = logging.getLogger(__name__)

_engine = None
_media_tmp: Path | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database.url, echo=False)
    return _engine


def get_media_tmp() -> Path:
    global _media_tmp
    if _media_tmp is None:
        settings = get_settings()
        root = Path(settings.media_root)
        tmp = root / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        _media_tmp = tmp
    return _media_tmp


def create_asset(kind: str, mime_type: str, suffix: str, contents: bytes | str = b"") -> MediaAsset:
    tmp = get_media_tmp()
    filename = f"{uuid4()}{suffix}"
    target = tmp / filename
    data = contents.encode() if isinstance(contents, str) else contents
    target.write_bytes(data)
    asset = MediaAsset(kind=kind, uri=f"/media/tmp/{filename}", mime_type=mime_type)
    with Session(get_engine()) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def update_job(job_id: str, *, status: JobStatus | None = None, progress: float | None = None, error: str | None = None, payload: dict | None = None, output_asset_id: str | None = None) -> None:
    try:
        with Session(get_engine()) as session:
            job = session.get(Job, UUID(job_id))
            if not job:
                logger.warning("Job not found for status update: %s", job_id)
                return
            if status:
                job.status = status
            if progress is not None:
                job.progress = progress
            if error:
                job.error = error
            if payload:
                merged = {**(job.payload or {}), **payload}
                job.payload = merged
            if output_asset_id:
                job.output_asset_id = UUID(output_asset_id) if output_asset_id else None
            session.add(job)
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to update job %s: %s", job_id, exc)


def _progress(task, status: str, progress: float = 0.0, **meta):
    payload = {"status": status, "progress": progress, **meta}
    try:
        task.update_state(state="PROGRESS", meta=payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Progress update failed: %s", exc)
    return payload


@celery_app.task(bind=True, name="tasks.ping")
def ping(self) -> str:
    _progress(self, "started", 0.0)
    return "pong"


@celery_app.task(bind=True, name="tasks.echo")
def echo(self, message: str) -> str:
    _progress(self, "started", 0.0, message=message)
    return message


@celery_app.task(bind=True, name="tasks.transcribe_video")
def transcribe_video(self, job_id: str, video_asset_id: str, config: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    transcript_text = f"Transcription for asset {video_asset_id}"
    asset = create_asset(kind="transcription", mime_type="text/plain", suffix=".txt", contents=transcript_text)
    result = {"video_asset_id": video_asset_id, "status": "transcribed", "config": config or {}, "output_asset_id": str(asset.id)}
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.generate_captions")
def generate_captions(self, job_id: str, video_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    captions = "1\n00:00:00,000 --> 00:00:02,000\nCaption placeholder\n"
    asset = create_asset(kind="subtitle", mime_type="text/vtt", suffix=".vtt", contents=captions)
    result = {"video_asset_id": video_asset_id, "status": "captions_generated", "options": options or {}, "output_asset_id": str(asset.id)}
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.translate_subtitles")
def translate_subtitles(self, job_id: str, subtitle_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, subtitle_asset_id=subtitle_asset_id)
    translated = "1\n00:00:00,000 --> 00:00:02,000\nTranslated placeholder\n"
    asset = create_asset(kind="subtitle", mime_type="text/vtt", suffix=".vtt", contents=translated)
    result = {"subtitle_asset_id": subtitle_asset_id, "status": "translated", "options": options or {}, "output_asset_id": str(asset.id)}
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, subtitle_asset_id=subtitle_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.render_styled_subtitles")
def render_styled_subtitles(self, job_id: str, video_asset_id: str, subtitle_asset_id: str, style: dict | None = None, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    rendered_marker = "styled-render-placeholder"
    asset = create_asset(kind="video", mime_type="text/plain", suffix=".txt", contents=rendered_marker)
    result = {
        "video_asset_id": video_asset_id,
        "subtitle_asset_id": subtitle_asset_id,
        "style": style or {},
        "options": options or {},
        "status": "styled_render",
        "output_asset_id": str(asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.generate_shorts")
def generate_shorts(self, job_id: str, video_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    clips = []
    max_clips = int(options.get("max_clips") or 3) if options else 3
    min_dur = options.get("min_duration") if options else None
    for idx in range(max_clips):
        clip_asset = create_asset(kind="video", mime_type="text/plain", suffix=".txt", contents=f"clip {idx+1} for {video_asset_id}")
        clips.append(
            {
                "id": f"{job_id}-clip-{idx+1}",
                "asset_id": str(clip_asset.id),
                "duration": min_dur,
                "score": 0.5 + idx * 0.1,
                "uri": clip_asset.uri,
                "subtitle_uri": None,
                "thumbnail_uri": None,
            }
        )
    summary_asset = create_asset(kind="video", mime_type="text/plain", suffix=".txt", contents="shorts package placeholder")
    result = {
        "video_asset_id": video_asset_id,
        "status": "shorts_generated",
        "options": options or {},
        "clip_assets": clips,
        "output_asset_id": str(summary_asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload={"clip_assets": clips, **(options or {})}, output_asset_id=str(summary_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.merge_video_audio")
def merge_video_audio(self, job_id: str, video_asset_id: str, audio_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    merged_asset = create_asset(kind="video", mime_type="text/plain", suffix=".txt", contents="merged av placeholder")
    result = {
        "video_asset_id": video_asset_id,
        "audio_asset_id": audio_asset_id,
        "options": options or {},
        "status": "merged",
        "output_asset_id": str(merged_asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(merged_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    return result


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
