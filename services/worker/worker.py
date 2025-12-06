import os
from celery import Celery

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery("reframe_worker", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.task_default_queue = "default"


@celery_app.task(name="tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="tasks.echo")
def echo(message: str) -> str:
    return message


@celery_app.task(name="tasks.transcribe_video")
def transcribe_video(video_asset_id: str, config: dict | None = None) -> dict:
    return {"video_asset_id": video_asset_id, "status": "transcribed", "config": config or {}}


@celery_app.task(name="tasks.generate_captions")
def generate_captions(video_asset_id: str, options: dict | None = None) -> dict:
    return {"video_asset_id": video_asset_id, "status": "captions_generated", "options": options or {}}


@celery_app.task(name="tasks.translate_subtitles")
def translate_subtitles(subtitle_asset_id: str, options: dict | None = None) -> dict:
    return {"subtitle_asset_id": subtitle_asset_id, "status": "translated", "options": options or {}}


@celery_app.task(name="tasks.render_styled_subtitles")
def render_styled_subtitles(video_asset_id: str, subtitle_asset_id: str, style: dict | None = None, options: dict | None = None) -> dict:
    return {
        "video_asset_id": video_asset_id,
        "subtitle_asset_id": subtitle_asset_id,
        "style": style or {},
        "options": options or {},
        "status": "styled_render",
    }


@celery_app.task(name="tasks.generate_shorts")
def generate_shorts(video_asset_id: str, options: dict | None = None) -> dict:
    return {"video_asset_id": video_asset_id, "status": "shorts_generated", "options": options or {}}


@celery_app.task(name="tasks.merge_video_audio")
def merge_video_audio(video_asset_id: str, audio_asset_id: str, options: dict | None = None) -> dict:
    return {
        "video_asset_id": video_asset_id,
        "audio_asset_id": audio_asset_id,
        "options": options or {},
        "status": "merged",
    }


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
