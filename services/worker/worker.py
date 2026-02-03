import base64
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Tuple
from uuid import UUID, uuid4

from sqlmodel import Session, create_engine

# Ensure app package is importable for shared models/config when running from services/.
def _find_repo_root(start: Path) -> Path:
    for candidate in [start.parent, *start.parents]:
        if (candidate / "apps" / "api").is_dir():
            return candidate
    return start.parent


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
API_PATH = REPO_ROOT / "apps" / "api"
if API_PATH.is_dir() and str(API_PATH) not in sys.path:
    sys.path.append(str(API_PATH))

MEDIA_CORE_SRC = REPO_ROOT / "packages" / "media-core" / "src"
if MEDIA_CORE_SRC.is_dir() and str(MEDIA_CORE_SRC) not in sys.path:
    sys.path.append(str(MEDIA_CORE_SRC))

from app.config import get_settings
from app.models import Job, JobStatus, MediaAsset
from celery import Celery

from media_core.segment.shorts import equal_splits, select_top
from media_core.subtitles.builder import GroupingConfig, group_words, to_ass, to_srt, to_vtt
from media_core.transcribe import (
    TranscriptionBackend,
    TranscriptionConfig,
    transcribe_faster_whisper,
    transcribe_noop,
    transcribe_openai_file,
    transcribe_whisper_cpp,
    transcribe_whisper_timestamped,
)
from media_core.translate.srt import translate_srt, translate_srt_bilingual
from media_core.translate.translator import LocalTranslator, NoOpTranslator
from media_core.video_edit.ffmpeg import cut_clip, merge_video_audio as ffmpeg_merge_video_audio, probe_media

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery("reframe_worker", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.task_default_queue = "default"

logger = logging.getLogger(__name__)

_engine = None
_media_tmp: Path | None = None

_FALLBACK_THUMBNAIL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database.url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, echo=False, connect_args=connect_args)
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


def create_asset(kind: str, mime_type: str, suffix: str, contents: bytes | str = b"", source_path: Path | None = None) -> MediaAsset:
    tmp = get_media_tmp()
    filename = f"{uuid4()}{suffix}"
    target = tmp / filename
    if source_path and source_path.exists():
        shutil.copy2(source_path, target)
    else:
        data = contents.encode() if isinstance(contents, str) else contents
        target.write_bytes(data)
    asset = MediaAsset(kind=kind, uri=f"/media/tmp/{filename}", mime_type=mime_type)
    with Session(get_engine()) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def create_asset_for_existing_file(*, kind: str, mime_type: str, file_path: Path) -> MediaAsset:
    tmp = get_media_tmp()
    resolved = file_path.resolve()
    try:
        resolved.relative_to(tmp.resolve())
    except Exception:
        raise ValueError(f"file_path must be under {tmp}, got {file_path}")
    uri = f"/media/tmp/{file_path.name}"
    asset = MediaAsset(kind=kind, uri=uri, mime_type=mime_type)
    with Session(get_engine()) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def new_tmp_file(suffix: str) -> Path:
    tmp = get_media_tmp()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    return tmp / f"{uuid4()}{suffix}"


def _truthy_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def offline_mode_enabled() -> bool:
    return _truthy_env("REFRAME_OFFLINE_MODE")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _transcribe_media(path: Path, config: TranscriptionConfig, *, warnings: list[str]):
    try:
        if config.backend == TranscriptionBackend.OPENAI_WHISPER:
            if offline_mode_enabled():
                warnings.append("Offline mode enabled; refusing openai_whisper and falling back to noop.")
                return transcribe_noop(str(path), config)
            return transcribe_openai_file(str(path), config)
        if config.backend == TranscriptionBackend.FASTER_WHISPER:
            return transcribe_faster_whisper(str(path), config)
        if config.backend == TranscriptionBackend.WHISPER_CPP:
            return transcribe_whisper_cpp(str(path), config)
        if config.backend in {TranscriptionBackend.WHISPER_TIMESTAMPED, TranscriptionBackend.WHISPERX}:
            return transcribe_whisper_timestamped(str(path), config)
        return transcribe_noop(str(path), config)
    except Exception as exc:
        warnings.append(f"Transcription backend {config.backend.value} failed; falling back to noop ({exc}).")
        return transcribe_noop(str(path), config)


def create_thumbnail_asset(video_path: Path | None, runner=None) -> MediaAsset:
    if not video_path or not video_path.exists():
        return create_asset(kind="image", mime_type="image/png", suffix=".png", contents=_FALLBACK_THUMBNAIL_PNG)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return create_asset(kind="image", mime_type="image/png", suffix=".png", contents=_FALLBACK_THUMBNAIL_PNG)

    thumb_tmp = get_media_tmp() / f"thumb-{uuid4()}.png"
    runner = runner or subprocess.run
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-ss",
        "0.5",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-1",
        str(thumb_tmp),
    ]
    try:
        runner(cmd, check=True, capture_output=True)
        if thumb_tmp.exists() and thumb_tmp.stat().st_size > 0:
            return create_asset(kind="image", mime_type="image/png", suffix=".png", source_path=thumb_tmp)
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Thumbnail generation failed: %s", exc)
    finally:
        try:
            thumb_tmp.unlink()
        except FileNotFoundError:
            pass
        except Exception:  # pragma: no cover - best effort
            logger.debug("Failed to remove temporary thumbnail: %s", thumb_tmp)

    return create_asset(kind="image", mime_type="image/png", suffix=".png", contents=_FALLBACK_THUMBNAIL_PNG)


def fetch_asset(asset_id: str) -> Tuple[Optional[MediaAsset], Optional[Path]]:
    try:
        uuid = UUID(asset_id)
    except Exception:
        return None, None
    settings = get_settings()
    with Session(get_engine()) as session:
        asset = session.get(MediaAsset, uuid)
        if not asset:
            return None, None
        uri_path = Path(asset.uri.lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == "media":
            uri_path = Path(*uri_path.parts[1:])
        file_path = Path(settings.media_root) / uri_path
        return asset, file_path


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
    opts = options or {}
    warnings: list[str] = []

    src_asset, src_path = fetch_asset(video_asset_id)
    if not src_path or not src_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    formats = opts.get("formats") if isinstance(opts, dict) else None
    requested = [str(f).lower() for f in formats] if isinstance(formats, list) else []
    output_format = next((fmt for fmt in requested if fmt in {"srt", "vtt", "ass"}), "srt")

    backend_raw = str(opts.get("backend") or "noop").strip().lower()
    if backend_raw == "whisper":
        warnings.append("backend 'whisper' is ambiguous; using noop (offline-safe). Use 'faster_whisper' or 'whisper_cpp'.")
        backend = TranscriptionBackend.NOOP
    else:
        try:
            backend = TranscriptionBackend(backend_raw)
        except ValueError:
            warnings.append(f"Unknown backend '{backend_raw}'; using noop.")
            backend = TranscriptionBackend.NOOP

    if backend == TranscriptionBackend.OPENAI_WHISPER and offline_mode_enabled():
        warnings.append("Offline mode enabled; refusing openai_whisper and using noop.")
        backend = TranscriptionBackend.NOOP

    language_raw = opts.get("language") or opts.get("source_language") or None
    language = None if not language_raw or str(language_raw).strip().lower() == "auto" else str(language_raw).strip()

    config = TranscriptionConfig(
        backend=backend,
        model=str(opts.get("model") or "whisper-1"),
        language=language,
        device=str(opts.get("device")) if opts.get("device") else None,
    )
    transcription = _transcribe_media(src_path, config, warnings=warnings)
    words = sorted(getattr(transcription, "words", []) or [], key=lambda w: (w.start, w.end))  # type: ignore[attr-defined]
    if not words:
        warnings.append("Transcription returned no words; falling back to noop output.")
        transcription = transcribe_noop(str(src_path), config)
        words = sorted(transcription.words or [], key=lambda w: (w.start, w.end))

    grouping = GroupingConfig(
        max_chars_per_line=int(opts.get("max_chars_per_line") or GroupingConfig.max_chars_per_line),
        max_words_per_line=int(opts.get("max_words_per_line") or GroupingConfig.max_words_per_line),
        max_duration=float(opts.get("max_duration") or GroupingConfig.max_duration),
        max_gap=float(opts.get("max_gap") or GroupingConfig.max_gap),
    )
    subtitle_lines = group_words(words, grouping)

    if output_format == "ass":
        payload = to_ass(subtitle_lines)
        mime = "text/ass"
        suffix = ".ass"
    elif output_format == "vtt":
        payload = to_vtt(subtitle_lines)
        mime = "text/vtt"
        suffix = ".vtt"
    else:
        payload = to_srt(subtitle_lines)
        mime = "text/srt"
        suffix = ".srt"

    asset = create_asset(kind="subtitle", mime_type=mime, suffix=suffix, contents=payload)
    result = {
        "video_asset_id": video_asset_id,
        "status": "captions_generated",
        "options": opts,
        "transcription_backend": backend.value,
        "model": config.model,
        "language": config.language,
        "warnings": warnings,
        "output_asset_id": str(asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.translate_subtitles")
def translate_subtitles(self, job_id: str, subtitle_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, subtitle_asset_id=subtitle_asset_id)
    opts = options or {}
    warnings: list[str] = []

    src_asset, src_path = fetch_asset(subtitle_asset_id)
    if not src_path or not src_path.exists():
        error = f"Subtitle asset file missing for {subtitle_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, subtitle_asset_id=subtitle_asset_id)
        return {"subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    target_language = str(opts.get("target_language") or "").strip()
    if not target_language:
        error = "Missing target_language"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, subtitle_asset_id=subtitle_asset_id)
        return {"subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    bilingual = _coerce_bool(opts.get("bilingual"))
    src_language = str(opts.get("source_language") or opts.get("src") or "en").strip()
    if not src_language or src_language.lower() == "auto":
        src_language = "en"

    try:
        translator = LocalTranslator(src_language, target_language)
    except Exception as exc:
        warnings.append(str(exc))
        translator = NoOpTranslator()

    text = src_path.read_text(encoding="utf-8", errors="replace")
    if src_path.suffix.lower() != ".srt":
        error = f"Only .srt subtitles are supported for translation currently (got {src_path.suffix or 'no extension'})."
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, subtitle_asset_id=subtitle_asset_id)
        return {"subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    try:
        if bilingual:
            translated = translate_srt_bilingual(text, translator, src_language, target_language)
        else:
            translated = translate_srt(text, translator, src_language, target_language)
    except Exception as exc:
        error = f"Subtitle translation failed: {exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, subtitle_asset_id=subtitle_asset_id)
        return {"subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    asset = create_asset(kind="subtitle", mime_type=src_asset.mime_type or "text/srt", suffix=".srt", contents=translated)
    result = {
        "subtitle_asset_id": subtitle_asset_id,
        "status": "translated",
        "options": opts,
        "target_language": target_language,
        "bilingual": bilingual,
        "warnings": warnings,
        "output_asset_id": str(asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, subtitle_asset_id=subtitle_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.render_styled_subtitles")
def render_styled_subtitles(self, job_id: str, video_asset_id: str, subtitle_asset_id: str, style: dict | None = None, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    src_asset, src_path = fetch_asset(video_asset_id)
    rendered_marker = src_path if src_path and src_path.exists() else None
    asset = create_asset(kind="video", mime_type=src_asset.mime_type if src_asset and src_asset.mime_type else "application/octet-stream", suffix=src_path.suffix if src_path else ".txt", contents="styled-render" if rendered_marker is None else b"", source_path=rendered_marker)
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
    opts = options or {}
    max_clips = int(opts.get("max_clips") or 3)
    min_duration = float(opts.get("min_duration") or 10.0)
    max_duration = float(opts.get("max_duration") or 60.0)
    use_subtitles = bool(opts.get("use_subtitles"))

    src_asset, src_path = fetch_asset(video_asset_id)
    if not src_path or not src_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    try:
        meta = probe_media(src_path)
        duration = float(meta.get("duration") or 0.0)
    except Exception as exc:
        error = f"Failed to probe media: {exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    candidates = equal_splits(duration, clip_length=max_duration)
    # Assign simple deterministic scores for now (heuristics/LLM scoring comes later).
    for idx, cand in enumerate(candidates):
        cand.score = 1.0 - (idx * 0.01)

    selected = select_top(candidates, max_segments=max_clips, min_duration=min_duration, max_duration=max_duration)
    if not selected:
        selected = candidates[:max_clips]

    clips: list[dict] = []
    for idx, seg in enumerate(selected):
        update_job(job_id, progress=0.1 + (idx / max(1, len(selected))) * 0.8)
        _progress(self, "processing", idx / max(1, len(selected)), clip_index=idx + 1)

        clip_path = new_tmp_file(".mp4")
        try:
            cut_clip(src_path, seg.start, seg.end, clip_path)
        except Exception as exc:
            error = f"Failed to cut clip {idx + 1}: {exc}"
            update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
            _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
            return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

        mime_type = src_asset.mime_type if src_asset and src_asset.mime_type else "video/mp4"
        clip_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=clip_path)

        thumb_asset = create_thumbnail_asset(clip_path)

        subtitle_asset = None
        if use_subtitles:
            subtitle_contents = (
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:02.000\n"
                f"Clip {idx + 1} subtitle placeholder\n"
            )
            subtitle_asset = create_asset(kind="subtitle", mime_type="text/vtt", suffix=".vtt", contents=subtitle_contents)

        clips.append(
            {
                "id": f"{job_id}-clip-{idx + 1}",
                "asset_id": str(clip_asset.id),
                "start": seg.start,
                "end": seg.end,
                "duration": round(seg.duration, 3),
                "score": seg.score,
                "uri": clip_asset.uri,
                "subtitle_uri": subtitle_asset.uri if subtitle_asset else None,
                "thumbnail_uri": thumb_asset.uri,
            }
        )

    manifest = {
        "video_asset_id": video_asset_id,
        "options": opts,
        "clip_assets": clips,
    }
    manifest_asset = create_asset(
        kind="shorts_manifest",
        mime_type="application/json",
        suffix=".json",
        contents=json.dumps(manifest, indent=2),
    )

    result = {"video_asset_id": video_asset_id, "status": "shorts_generated", "clip_assets": clips, "output_asset_id": str(manifest_asset.id)}
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload={"clip_assets": clips, **opts}, output_asset_id=str(manifest_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.merge_video_audio")
def merge_video_audio(self, job_id: str, video_asset_id: str, audio_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    opts = options or {}
    video_asset, video_path = fetch_asset(video_asset_id)
    audio_asset, audio_path = fetch_asset(audio_asset_id)

    if not video_path or not video_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "audio_asset_id": audio_asset_id, "status": "failed", "error": error}

    if not audio_path or not audio_path.exists():
        error = f"Audio asset file missing for {audio_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, audio_asset_id=audio_asset_id)
        return {"video_asset_id": video_asset_id, "audio_asset_id": audio_asset_id, "status": "failed", "error": error}

    output_path = new_tmp_file(".mp4")
    try:
        ffmpeg_merge_video_audio(
            video_path,
            audio_path,
            output_path,
            offset=float(opts.get("offset") or 0.0),
            ducking=opts.get("ducking"),
            normalize=bool(opts.get("normalize", True)),
        )
    except Exception as exc:
        error = f"Merge failed: {exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
        return {"video_asset_id": video_asset_id, "audio_asset_id": audio_asset_id, "status": "failed", "error": error}

    mime_type = video_asset.mime_type if video_asset and video_asset.mime_type else "video/mp4"
    merged_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=output_path)

    result = {
        "video_asset_id": video_asset_id,
        "audio_asset_id": audio_asset_id,
        "options": opts,
        "status": "merged",
        "output_asset_id": str(merged_asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(merged_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    return result


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
