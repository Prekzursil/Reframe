import logging
import os
from celery import Celery

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery("reframe_worker", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.task_default_queue = "default"

logger = logging.getLogger(__name__)


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
def transcribe_video(self, video_asset_id: str, config: dict | None = None) -> dict:
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    result = {"video_asset_id": video_asset_id, "status": "transcribed", "config": config or {}}
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.generate_captions")
def generate_captions(self, video_asset_id: str, options: dict | None = None) -> dict:
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    result = {"video_asset_id": video_asset_id, "status": "captions_generated", "options": options or {}}
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.translate_subtitles")
def translate_subtitles(self, subtitle_asset_id: str, options: dict | None = None) -> dict:
    _progress(self, "started", 0.0, subtitle_asset_id=subtitle_asset_id)
    result = {"subtitle_asset_id": subtitle_asset_id, "status": "translated", "options": options or {}}
    _progress(self, "completed", 1.0, subtitle_asset_id=subtitle_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.render_styled_subtitles")
def render_styled_subtitles(self, video_asset_id: str, subtitle_asset_id: str, style: dict | None = None, options: dict | None = None) -> dict:
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    result = {
        "video_asset_id": video_asset_id,
        "subtitle_asset_id": subtitle_asset_id,
        "style": style or {},
        "options": options or {},
        "status": "styled_render",
    }
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.generate_shorts")
def generate_shorts(self, video_asset_id: str, options: dict | None = None) -> dict:
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    result = {"video_asset_id": video_asset_id, "status": "shorts_generated", "options": options or {}}
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.merge_video_audio")
def merge_video_audio(self, video_asset_id: str, audio_asset_id: str, options: dict | None = None) -> dict:
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    result = {
        "video_asset_id": video_asset_id,
        "audio_asset_id": audio_asset_id,
        "options": options or {},
        "status": "merged",
    }
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    return result


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
