import base64
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, TypeVar
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlmodel import Session, create_engine, select

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
from app.local_queue import dispatch_task as dispatch_local_task, is_local_queue_mode
from app.billing import get_plan_policy
from app.models import (
    AutomationRunEvent,
    Job,
    JobStatus,
    MediaAsset,
    PublishConnection,
    PublishJob,
    Subscription,
    UsageEvent,
    UsageLedgerEntry,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowStepStatus,
    WorkflowTemplate,
)
from app.storage import LocalStorageBackend, get_storage, is_remote_uri
from celery import Celery
from kombu import Queue

from media_core.segment.shorts import HeuristicWeights, equal_splits, score_segments_heuristic, score_segments_llm, select_top
from media_core.diarize import DiarizationBackend, DiarizationConfig, assign_speakers_to_lines, diarize_audio
from media_core.subtitles.builder import GroupingConfig, SubtitleLine, group_words, to_ass, to_ass_karaoke, to_srt, to_vtt
from media_core.subtitles.vtt import parse_vtt
from media_core.transcribe import (
    TranscriptionBackend,
    TranscriptionConfig,
    transcribe_faster_whisper,
    transcribe_noop,
    transcribe_openai_file,
    transcribe_whisper_cpp,
    transcribe_whisper_timestamped,
)
from media_core.transcribe.models import Word
from media_core.translate.srt import parse_srt, translate_srt, translate_srt_bilingual
from media_core.translate.translator import CloudTranslator, LocalTranslator, NoOpTranslator
from media_core.video_edit.ffmpeg import cut_clip, detect_silence, merge_video_audio as ffmpeg_merge_video_audio, probe_media

try:
    from .groq_client import get_groq_chat_client_from_env
except Exception:  # pragma: no cover - supports running worker as a top-level module
    from groq_client import get_groq_chat_client_from_env  # type: ignore

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery("reframe_worker", broker=BROKER_URL, backend=RESULT_BACKEND)


def _env_truthy(name: str) -> bool:
    value = (os.getenv(name) or os.getenv(f"REFRAME_{name}") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


CPU_QUEUE = (os.getenv("REFRAME_CELERY_QUEUE_CPU") or "cpu").strip() or "cpu"
GPU_QUEUE = (os.getenv("REFRAME_CELERY_QUEUE_GPU") or "gpu").strip() or "gpu"
DEFAULT_QUEUE = (os.getenv("REFRAME_CELERY_QUEUE_DEFAULT") or "default").strip() or "default"
celery_app.conf.task_default_queue = CPU_QUEUE
celery_app.conf.task_queues = (
    Queue(DEFAULT_QUEUE),
    Queue(CPU_QUEUE),
    Queue(GPU_QUEUE),
)


def _dispatch_task(task_name: str, args: list[str | dict | None], queue: str) -> SimpleNamespace:
    if is_local_queue_mode():
        task_id = dispatch_local_task(task_name, *args, queue=queue)
        return SimpleNamespace(id=task_id)
    return celery_app.send_task(task_name, args=args, queue=queue)

logger = logging.getLogger(__name__)

_engine = None
_media_tmp: Path | None = None

T = TypeVar("T")


CAPTION_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    "balanced": {},
    "readable": {
        "max_chars_per_line": 36,
        "max_words_per_line": 10,
        "max_duration": 5.5,
        "max_gap": 0.55,
        "max_chars_per_second": 26.0,
        "sentence_break_on_punctuation": True,
        "sentence_break_min_gap": 0.05,
    },
    "high_impact": {
        "max_chars_per_line": 28,
        "max_words_per_line": 6,
        "max_duration": 3.8,
        "max_gap": 0.45,
        "max_chars_per_second": 22.0,
        "sentence_break_on_punctuation": True,
        "sentence_break_min_gap": 0.03,
    },
}


def _retry_max_attempts() -> int:
    raw = (os.getenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS") or "").strip()
    try:
        value = int(raw) if raw else 2
    except ValueError:
        value = 2
    return max(1, value)


def _retry_base_delay_seconds() -> float:
    raw = (os.getenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else 1.0
    except ValueError:
        value = 1.0
    return max(0.0, value)


def _run_ffmpeg_with_retries(*, job_id: str, step: str, fn: Callable[[], T]) -> T:
    max_attempts = _retry_max_attempts()
    base_delay = _retry_base_delay_seconds()
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            if attempt >= max_attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
            update_job(
                job_id,
                payload={
                    "retry_step": step,
                    "retry_attempt": attempt,
                    "retry_max_attempts": max_attempts,
                    "retry_delay_seconds": round(delay, 3),
                    "retry_error": (stderr[-1000:] or str(exc))[:1000],
                },
            )
            if delay > 0:
                time.sleep(delay)
        except Exception as exc:
            last_exc = exc
            raise

    # Should not reach here.
    if last_exc:
        raise last_exc
    raise RuntimeError("Retry loop failed without an exception")

_FALLBACK_THUMBNAIL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
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


def _worker_storage():
    settings = get_settings()
    return get_storage(media_root=settings.media_root)


def _worker_rel_dir(*, storage: Any, org_id: UUID | None) -> str:
    if org_id and not isinstance(storage, LocalStorageBackend):
        return f"{org_id}/tmp"
    return "tmp"


def create_asset(
    kind: str,
    mime_type: str,
    suffix: str,
    contents: bytes | str = b"",
    source_path: Path | None = None,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> MediaAsset:
    storage = _worker_storage()
    tmp = get_media_tmp()
    filename = f"{uuid4()}{suffix}"
    target = tmp / filename
    if source_path and source_path.exists():
        shutil.copy2(source_path, target)
    else:
        data = contents.encode() if isinstance(contents, str) else contents
        target.write_bytes(data)
    rel_dir = _worker_rel_dir(storage=storage, org_id=org_id)
    uri = storage.write_file(rel_dir=rel_dir, filename=filename, source_path=target, content_type=mime_type)
    asset = MediaAsset(
        kind=kind,
        uri=uri,
        mime_type=mime_type,
        project_id=project_id,
        org_id=org_id,
        owner_user_id=owner_user_id,
    )
    with Session(get_engine()) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def create_asset_for_existing_file(
    *,
    kind: str,
    mime_type: str,
    file_path: Path,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> MediaAsset:
    storage = _worker_storage()
    tmp = get_media_tmp()
    resolved = file_path.resolve()
    try:
        resolved.relative_to(tmp.resolve())
    except Exception:
        raise ValueError(f"file_path must be under {tmp}, got {file_path}")
    rel_dir = _worker_rel_dir(storage=storage, org_id=org_id)
    uri = storage.write_file(rel_dir=rel_dir, filename=file_path.name, source_path=file_path, content_type=mime_type)
    asset = MediaAsset(
        kind=kind,
        uri=uri,
        mime_type=mime_type,
        project_id=project_id,
        org_id=org_id,
        owner_user_id=owner_user_id,
    )
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
    return _env_truthy(name)


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


def _coerce_bool_with_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return _coerce_bool(value)


def _hex_to_ass_color(value: Any, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    raw = value.strip()
    if not raw:
        return default
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return default
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        return default
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _is_http_uri(uri: str) -> bool:
    lowered = (uri or "").strip().lower()
    return lowered.startswith(("http://", "https://"))


def _download_remote_uri_to_tmp(*, uri: str, mime_type: str | None = None) -> Path:
    if offline_mode_enabled():
        raise RuntimeError("REFRAME_OFFLINE_MODE is enabled; refusing to download remote assets.")

    uri = (uri or "").strip()
    if not _is_http_uri(uri):
        raise ValueError(f"Not a remote http(s) uri: {uri}")

    parsed = urllib.parse.urlparse(uri)
    suffix = Path(parsed.path).suffix
    if not suffix and mime_type:
        suffix = mimetypes.guess_extension(mime_type) or ""
    if not suffix:
        suffix = ".bin"

    dest = new_tmp_file(suffix)
    request = urllib.request.Request(uri, headers={"User-Agent": "reframe-worker"})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as f:  # noqa: S310 - intended outbound request (gated)
        shutil.copyfileobj(response, f)

    if not dest.exists() or dest.stat().st_size <= 0:
        raise RuntimeError(f"Downloaded asset is empty: {uri}")
    return dest


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


def _extract_audio_wav_for_diarization(video_path: Path, output_path: Path, runner=None) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found in PATH")
    runner = runner or subprocess.run
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    runner(cmd, check=True, capture_output=True)


def create_thumbnail_asset(
    video_path: Path | None,
    runner=None,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> MediaAsset:
    asset_kwargs: dict[str, UUID] = {}
    if project_id is not None:
        asset_kwargs["project_id"] = project_id
    if org_id is not None:
        asset_kwargs["org_id"] = org_id
    if owner_user_id is not None:
        asset_kwargs["owner_user_id"] = owner_user_id

    if not video_path or not video_path.exists():
        return create_asset(
            kind="image",
            mime_type="image/png",
            suffix=".png",
            contents=_FALLBACK_THUMBNAIL_PNG,
            **asset_kwargs,
        )

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return create_asset(
            kind="image",
            mime_type="image/png",
            suffix=".png",
            contents=_FALLBACK_THUMBNAIL_PNG,
            **asset_kwargs,
        )

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
            return create_asset(
                kind="image",
                mime_type="image/png",
                suffix=".png",
                source_path=thumb_tmp,
                **asset_kwargs,
            )
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Thumbnail generation failed: %s", exc)
    finally:
        try:
            thumb_tmp.unlink()
        except FileNotFoundError:
            pass
        except Exception:  # pragma: no cover - best effort
            logger.debug("Failed to remove temporary thumbnail: %s", thumb_tmp)

    return create_asset(
        kind="image",
        mime_type="image/png",
        suffix=".png",
        contents=_FALLBACK_THUMBNAIL_PNG,
        **asset_kwargs,
    )


def fetch_asset(asset_id: str) -> Tuple[Optional[MediaAsset], Optional[Path]]:
    try:
        uuid = UUID(asset_id)
    except Exception:
        return None, None
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    with Session(get_engine()) as session:
        asset = session.get(MediaAsset, uuid)
        if not asset:
            return None, None
        if asset.uri and is_remote_uri(asset.uri):
            try:
                download_uri = (asset.uri or "").strip()
                if not _is_http_uri(download_uri):
                    resolved = storage.get_download_url(download_uri)
                    if not resolved:
                        logger.warning("Could not resolve remote download URL for asset %s (%s)", asset.id, asset.uri)
                        return asset, None
                    download_uri = resolved
                return asset, _download_remote_uri_to_tmp(uri=download_uri, mime_type=asset.mime_type)
            except Exception as exc:  # pragma: no cover - optional best-effort behavior
                logger.warning("Failed to download remote asset %s: %s", asset.uri, exc)
                return asset, None
        uri_path = Path(asset.uri.lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == "media":
            uri_path = Path(*uri_path.parts[1:])
        file_path = Path(settings.media_root) / uri_path
        return asset, file_path


def _record_usage_event(
    session: Session,
    *,
    org_id: UUID | None,
    user_id: UUID | None,
    job_id: UUID,
    metric: str,
    quantity: float,
    details: dict | None = None,
) -> None:
    if not org_id:
        return
    plan_code = "free"
    sub = session.exec(select(Subscription).where(Subscription.org_id == org_id)).first()
    if sub and sub.plan_code:
        plan_code = sub.plan_code
    policy = get_plan_policy(plan_code)

    estimated_cost_cents = 0
    unit = "count"
    if metric == "job_minutes":
        unit = "minute"
        estimated_cost_cents = int(round(float(quantity) * float(policy.overage_per_minute_cents)))
    elif metric == "storage_bytes":
        unit = "byte"
    elif metric == "jobs_completed":
        unit = "count"

    event = UsageEvent(
        org_id=org_id,
        user_id=user_id,
        job_id=job_id,
        metric=metric,
        quantity=float(quantity),
        details=details or {},
    )
    session.add(event)
    session.add(
        UsageLedgerEntry(
            org_id=org_id,
            user_id=user_id,
            job_id=job_id,
            metric=metric,
            unit=unit,
            quantity=float(quantity),
            estimated_cost_cents=estimated_cost_cents,
            payload={**(details or {}), "plan_code": plan_code},
        )
    )


def _asset_size_bytes(asset: MediaAsset) -> int:
    if not asset.uri or is_remote_uri(asset.uri):
        return 0
    settings = get_settings()
    uri_path = Path(asset.uri.lstrip("/"))
    if uri_path.parts and uri_path.parts[0] == "media":
        uri_path = Path(*uri_path.parts[1:])
    path = Path(settings.media_root) / uri_path
    try:
        return int(path.stat().st_size) if path.exists() else 0
    except OSError:
        return 0


_RETENTION_DAYS_BY_PLAN: dict[str, int] = {
    "free": 14,
    "pro": 30,
    "enterprise": 90,
}


def _retention_days_for_plan(plan_code: str) -> int:
    normalized = (plan_code or "").strip().lower()
    base = _RETENTION_DAYS_BY_PLAN.get(normalized, _RETENTION_DAYS_BY_PLAN["free"])
    env_key = f"REFRAME_RETENTION_{normalized.upper()}_DAYS" if normalized else "REFRAME_RETENTION_FREE_DAYS"
    raw = (os.getenv(env_key) or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return base
    return base


def _is_older_than_retention(*, created_at: datetime | None, plan_code: str, now: datetime | None = None) -> bool:
    if created_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_retention_days_for_plan(plan_code))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    return created_at < cutoff


def _job_related_asset_ids(job: Job) -> set[UUID]:
    out: set[UUID] = set()
    if job.output_asset_id:
        out.add(job.output_asset_id)
    payload = job.payload or {}
    if isinstance(payload, dict):
        clips = payload.get("clip_assets")
        if isinstance(clips, list):
            for item in clips:
                if not isinstance(item, dict):
                    continue
                for key in ("asset_id", "thumbnail_asset_id", "subtitle_asset_id", "styled_asset_id"):
                    raw = item.get(key)
                    if not raw:
                        continue
                    try:
                        out.add(UUID(str(raw)))
                    except Exception:
                        continue
    return out


def _asset_referenced_by_jobs(session: Session, asset_id: UUID) -> bool:
    query = select(Job.id).where((Job.input_asset_id == asset_id) | (Job.output_asset_id == asset_id)).limit(1)
    return session.exec(query).first() is not None


def _delete_asset(session: Session, asset: MediaAsset) -> None:
    if asset.uri:
        storage = _worker_storage()
        try:
            storage.delete_uri(asset.uri)
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.debug("Failed to delete asset URI %s: %s", asset.uri, exc)
    session.delete(asset)


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: float | None = None,
    error: str | None = None,
    payload: dict | None = None,
    output_asset_id: str | None = None,
) -> None:
    try:
        with Session(get_engine()) as session:
            job = session.get(Job, UUID(job_id))
            if not job:
                logger.warning("Job not found for status update: %s", job_id)
                return
            previous_status = job.status
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

            if job.status == JobStatus.completed and previous_status != JobStatus.completed:
                _record_usage_event(
                    session,
                    org_id=job.org_id,
                    user_id=job.owner_user_id,
                    job_id=job.id,
                    metric="jobs_completed",
                    quantity=1.0,
                    details={"job_type": job.job_type},
                )
                if job.output_asset_id:
                    output = session.get(MediaAsset, job.output_asset_id)
                    if output:
                        minutes = max(0.0, float(output.duration or 0.0) / 60.0)
                        if minutes > 0:
                            _record_usage_event(
                                session,
                                org_id=job.org_id,
                                user_id=job.owner_user_id,
                                job_id=job.id,
                                metric="job_minutes",
                                quantity=minutes,
                                details={"job_type": job.job_type, "asset_id": str(output.id)},
                            )
                        size_bytes = _asset_size_bytes(output)
                        if size_bytes > 0:
                            _record_usage_event(
                                session,
                                org_id=job.org_id,
                                user_id=job.owner_user_id,
                                job_id=job.id,
                                metric="storage_bytes",
                                quantity=float(size_bytes),
                                details={"job_type": job.job_type, "asset_id": str(output.id)},
                            )
            session.add(job)
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to update job %s: %s", job_id, exc)


def get_job_context(job_id: str) -> dict[str, UUID | None]:
    try:
        with Session(get_engine()) as session:
            job = session.get(Job, UUID(job_id))
            if not job:
                return {"project_id": None, "org_id": None, "owner_user_id": None}
            return {
                "project_id": job.project_id,
                "org_id": job.org_id,
                "owner_user_id": job.owner_user_id,
            }
    except Exception:
        return {"project_id": None, "org_id": None, "owner_user_id": None}


def get_job_project_id(job_id: str) -> UUID | None:
    return get_job_context(job_id).get("project_id")


def _job_asset_kwargs(job_id: str) -> dict[str, UUID]:
    ctx = get_job_context(job_id)
    out: dict[str, UUID] = {}
    for key in ("project_id", "org_id", "owner_user_id"):
        value = ctx.get(key)
        if value is not None:
            out[key] = value
    return out


def _progress(task, status: str, progress: float = 0.0, **meta):
    payload = {"status": status, "progress": progress, **meta}
    try:
        task.update_state(state="PROGRESS", meta=payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Progress update failed: %s", exc)
    return payload


SUPPORTED_PUBLISH_PROVIDERS = {"youtube", "tiktok", "instagram", "facebook"}


def _publish_provider_from_step(step_type: str, step_payload: dict) -> str:
    normalized = (step_type or "").strip().lower()
    if normalized.startswith("publish_"):
        provider = normalized.split("_", 1)[1].strip()
    elif normalized == "publish":
        provider = str(step_payload.get("provider") or "").strip().lower()
    else:
        raise ValueError(f"Unsupported publish step type: {step_type}")
    if provider not in SUPPORTED_PUBLISH_PROVIDERS:
        raise ValueError(f"Unsupported publish provider: {provider}")
    return provider


def _publish_result_for_provider(
    *,
    provider: str,
    connection: PublishConnection,
    asset: MediaAsset,
    payload: dict,
) -> dict[str, str]:
    base_external = f"{provider}_{str(asset.id).replace('-', '')[:12]}"
    title = str(payload.get("title") or payload.get("caption") or "").strip()
    if provider == "youtube":
        return {
            "external_post_id": base_external,
            "published_url": f"https://www.youtube.com/watch?v={base_external}",
            "status": "published",
            "provider_status": "video_uploaded",
            "title": title or "Untitled upload",
        }
    if provider == "tiktok":
        return {
            "external_post_id": base_external,
            "published_url": f"https://www.tiktok.com/@{(connection.account_label or 'creator').replace(' ', '').lower()}/video/{base_external}",
            "status": "published",
            "provider_status": "post_live",
            "title": title or "TikTok upload",
        }
    if provider == "instagram":
        return {
            "external_post_id": base_external,
            "published_url": f"https://www.instagram.com/p/{base_external}/",
            "status": "published",
            "provider_status": "media_published",
            "title": title or "Instagram upload",
        }
    if provider == "facebook":
        return {
            "external_post_id": base_external,
            "published_url": f"https://www.facebook.com/{(connection.external_account_id or 'reframe')}/posts/{base_external}",
            "status": "published",
            "provider_status": "post_published",
            "title": title or "Facebook upload",
        }
    raise ValueError(f"Unsupported publish provider: {provider}")


def _dispatch_pipeline_step(
    *,
    job: Job,
    run: WorkflowRun,
    step_type: str,
    input_asset_id: UUID | None,
    step_payload: dict,
) -> str:
    if not input_asset_id and step_type in {"captions", "shorts", "translate_subtitles"}:
        raise ValueError(f"Workflow step `{step_type}` is missing input asset")

    if step_type == "captions":
        result = _dispatch_task("tasks.generate_captions", args=[str(job.id), str(input_asset_id), step_payload], queue=CPU_QUEUE)
        return str(result.id)
    if step_type == "translate_subtitles":
        result = _dispatch_task("tasks.translate_subtitles", args=[str(job.id), str(input_asset_id), step_payload], queue=CPU_QUEUE)
        return str(result.id)
    if step_type == "style_subtitles":
        video_asset_id = str(step_payload.get("video_asset_id") or run.input_asset_id or "")
        subtitle_asset_id = str(step_payload.get("subtitle_asset_id") or input_asset_id or "")
        style = step_payload.get("style") if isinstance(step_payload.get("style"), dict) else {}
        options = {"preview_seconds": step_payload.get("preview_seconds")}
        result = _dispatch_task(
            "tasks.render_styled_subtitles",
            args=[str(job.id), video_asset_id, subtitle_asset_id, style, options],
            queue=CPU_QUEUE,
        )
        return str(result.id)
    if step_type == "shorts":
        result = _dispatch_task("tasks.generate_shorts", args=[str(job.id), str(input_asset_id), step_payload], queue=CPU_QUEUE)
        return str(result.id)
    if step_type in {"publish", "publish_youtube", "publish_tiktok", "publish_instagram", "publish_facebook"}:
        provider = _publish_provider_from_step(step_type, step_payload)
        connection_id = str(step_payload.get("connection_id") or "").strip()
        if not connection_id:
            raise ValueError("Publish step requires payload.connection_id")
        publish_asset_id = str(step_payload.get("asset_id") or input_asset_id or "").strip()
        if not publish_asset_id:
            raise ValueError("Publish step requires an asset_id or workflow input asset")
        task_payload = dict(step_payload)
        task_payload.setdefault("source_workflow_job_id", str(job.id))
        result = _dispatch_task(
            "tasks.publish_asset",
            args=[None, provider, connection_id, publish_asset_id, str(run.id), task_payload],
            queue=CPU_QUEUE,
        )
        return str(result.id)
    raise ValueError(f"Unsupported workflow step type: {step_type}")


@celery_app.task(bind=True, name="tasks.publish_asset")
def publish_asset(
    self,
    publish_job_id: str | None = None,
    provider: str | None = None,
    connection_id: str | None = None,
    asset_id: str | None = None,
    workflow_run_id: str | None = None,
    payload: dict | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    details = dict(payload or {})

    with Session(get_engine()) as session:
        workflow_uuid: UUID | None = None
        if workflow_run_id:
            try:
                workflow_uuid = UUID(workflow_run_id)
            except Exception:
                workflow_uuid = None

        job: PublishJob | None = None
        if publish_job_id:
            try:
                job = session.get(PublishJob, UUID(publish_job_id))
            except Exception:
                return {"status": "invalid_publish_job_id", "publish_job_id": publish_job_id}
            if not job:
                return {"status": "missing", "publish_job_id": publish_job_id}
        else:
            if not provider or not connection_id or not asset_id:
                return {"status": "failed", "error": "provider, connection_id, and asset_id are required when publish_job_id is omitted"}
            try:
                connection_uuid = UUID(connection_id)
                asset_uuid = UUID(asset_id)
            except Exception:
                return {"status": "failed", "error": "connection_id and asset_id must be valid UUIDs"}

            connection = session.get(PublishConnection, connection_uuid)
            asset = session.get(MediaAsset, asset_uuid)
            if not connection:
                return {"status": "failed", "error": "publish_connection_missing"}
            if not asset:
                return {"status": "failed", "error": "asset_missing"}
            provider_normalized = str(provider).strip().lower()
            if provider_normalized not in SUPPORTED_PUBLISH_PROVIDERS:
                return {"status": "failed", "error": f"unsupported_provider:{provider_normalized}"}

            job = PublishJob(
                org_id=connection.org_id,
                user_id=connection.user_id,
                provider=provider_normalized,
                connection_id=connection.id,
                asset_id=asset.id,
                status="queued",
                payload={**details, "workflow_run_id": str(workflow_uuid) if workflow_uuid else None},
                retry_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            session.refresh(job)

        connection = session.get(PublishConnection, job.connection_id)
        asset = session.get(MediaAsset, job.asset_id)
        if not connection or connection.revoked_at is not None:
            job.status = "failed"
            job.error = "publish_connection_invalid"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.add(
                AutomationRunEvent(
                    org_id=job.org_id,
                    workflow_run_id=workflow_uuid,
                    publish_job_id=job.id,
                    step_name=f"publish.job.{job.provider}",
                    status="failed",
                    message="connection_missing_or_revoked",
                    payload={},
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return {"status": "failed", "publish_job_id": str(job.id), "error": job.error}
        if not asset:
            job.status = "failed"
            job.error = "publish_asset_missing"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            return {"status": "failed", "publish_job_id": str(job.id), "error": job.error}

        task_id = str(getattr(self.request, "id", "") or "").strip() or None
        if task_id:
            job.task_id = task_id
        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.add(
            AutomationRunEvent(
                org_id=job.org_id,
                workflow_run_id=workflow_uuid,
                publish_job_id=job.id,
                step_name=f"publish.job.{job.provider}",
                status="running",
                message=None,
                payload={"task_id": task_id},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        try:
            result = _publish_result_for_provider(provider=job.provider, connection=connection, asset=asset, payload=dict(job.payload or {}))
            job.status = "completed"
            job.error = None
            job.external_post_id = result.get("external_post_id")
            job.published_url = result.get("published_url")
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.add(
                AutomationRunEvent(
                    org_id=job.org_id,
                    workflow_run_id=workflow_uuid,
                    publish_job_id=job.id,
                    step_name=f"publish.job.{job.provider}",
                    status="completed",
                    message=result.get("provider_status"),
                    payload=result,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return {
                "status": "completed",
                "publish_job_id": str(job.id),
                "provider": job.provider,
                "external_post_id": job.external_post_id,
                "published_url": job.published_url,
            }
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.add(
                AutomationRunEvent(
                    org_id=job.org_id,
                    workflow_run_id=workflow_uuid,
                    publish_job_id=job.id,
                    step_name=f"publish.job.{job.provider}",
                    status="failed",
                    message=str(exc),
                    payload={},
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return {"status": "failed", "publish_job_id": str(job.id), "error": str(exc)}


@celery_app.task(bind=True, name="tasks.run_workflow_pipeline")
def run_workflow_pipeline(self, workflow_run_id: str) -> dict:
    try:
        run_uuid = UUID(workflow_run_id)
    except Exception:
        return {"status": "invalid_run_id", "workflow_run_id": workflow_run_id}

    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        run = session.get(WorkflowRun, run_uuid)
        if not run:
            return {"status": "missing", "workflow_run_id": workflow_run_id}
        if run.status == WorkflowRunStatus.cancelled:
            return {"status": "cancelled", "workflow_run_id": workflow_run_id}

        template = session.get(WorkflowTemplate, run.template_id)
        if not template:
            run.status = WorkflowRunStatus.failed
            run.updated_at = now
            run.payload = {**(run.payload or {}), "error": "Workflow template not found"}
            session.add(run)
            session.commit()
            return {"status": "failed", "workflow_run_id": workflow_run_id, "error": "template_missing"}

        run.status = WorkflowRunStatus.running
        run.updated_at = now
        session.add(run)
        session.commit()

        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.order_index.asc())
        ).all()
        current_input_asset_id = run.input_asset_id
        dispatched_jobs: list[dict[str, str]] = []

        for step in steps:
            refreshed_run = session.get(WorkflowRun, run.id)
            if refreshed_run and refreshed_run.status == WorkflowRunStatus.cancelled:
                step.status = WorkflowStepStatus.cancelled
                step.updated_at = datetime.now(timezone.utc)
                session.add(step)
                session.commit()
                continue

            step.status = WorkflowStepStatus.running
            step.updated_at = datetime.now(timezone.utc)
            session.add(step)
            session.commit()

            step_payload = dict(step.payload or {})
            try:
                job = Job(
                    job_type=step.step_type,
                    status=JobStatus.queued,
                    progress=0.0,
                    input_asset_id=current_input_asset_id,
                    payload=step_payload,
                    project_id=run.project_id,
                    org_id=run.org_id,
                    owner_user_id=run.owner_user_id,
                )
                session.add(job)
                session.commit()
                session.refresh(job)

                task_id = _dispatch_pipeline_step(
                    job=job,
                    run=run,
                    step_type=step.step_type,
                    input_asset_id=current_input_asset_id,
                    step_payload=step_payload,
                )
                job.task_id = task_id
                session.add(job)

                step.status = WorkflowStepStatus.completed
                step.updated_at = datetime.now(timezone.utc)
                step.payload = {**step_payload, "job_id": str(job.id), "task_id": task_id}
                session.add(step)
                session.commit()

                dispatched_jobs.append({"step_type": step.step_type, "job_id": str(job.id), "task_id": task_id})
            except Exception as exc:
                step.status = WorkflowStepStatus.failed
                step.updated_at = datetime.now(timezone.utc)
                step.payload = {**step_payload, "error": str(exc)}
                session.add(step)
                run.status = WorkflowRunStatus.failed
                run.updated_at = datetime.now(timezone.utc)
                run.payload = {**(run.payload or {}), "error": f"Step `{step.step_type}` failed to dispatch: {exc}"}
                session.add(run)
                session.commit()
                return {
                    "status": "failed",
                    "workflow_run_id": workflow_run_id,
                    "step_id": str(step.id),
                    "error": str(exc),
                }

        run.status = WorkflowRunStatus.completed
        run.updated_at = datetime.now(timezone.utc)
        run.payload = {**(run.payload or {}), "dispatched_jobs": dispatched_jobs}
        session.add(run)
        session.commit()

        return {"status": "completed", "workflow_run_id": workflow_run_id, "dispatched_jobs": dispatched_jobs}


@celery_app.task(bind=True, name="tasks.ping")
def ping(self) -> str:
    _progress(self, "started", 0.0)
    return "pong"


@celery_app.task(bind=True, name="tasks.echo")
def echo(self, message: str) -> str:
    _progress(self, "started", 0.0, message=message)
    return message


@celery_app.task(bind=True, name="tasks.system_info")
def system_info(self) -> dict:
    """Return basic worker capability info for the web UI diagnostics panel."""
    _progress(self, "started", 0.0)

    def has_module(name: str) -> bool:
        try:
            __import__(name)
            return True
        except Exception:
            return False

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    ffmpeg_version = None
    if ffmpeg:
        try:
            out = subprocess.check_output([ffmpeg, "-version"], text=True, stderr=subprocess.STDOUT)
            ffmpeg_version = (out.splitlines()[0] if out else "").strip() or None
        except Exception:
            ffmpeg_version = None

    info = {
        "python": {
            "version": sys.version.split()[0],
        },
        "env": {
            "offline_mode": offline_mode_enabled(),
            "media_root": str(get_settings().media_root),
            "hf_token_set": bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")),
        },
        "ffmpeg": {
            "present": bool(ffmpeg and ffprobe),
            "ffmpeg_path": ffmpeg,
            "ffprobe_path": ffprobe,
            "version": ffmpeg_version,
        },
        "features": {
            "transcribe_faster_whisper": has_module("faster_whisper"),
            "transcribe_whisper_cpp": has_module("whispercpp"),
            "translate_argos": has_module("argostranslate"),
            "diarize_pyannote": has_module("pyannote.audio"),
            "diarize_speechbrain": has_module("speechbrain"),
        },
        "cache": {
            "hf_home": os.getenv("HF_HOME") or None,
            "hf_hub_cache": os.getenv("HUGGINGFACE_HUB_CACHE") or None,
        },
    }

    _progress(self, "completed", 1.0)
    return info


@celery_app.task(bind=True, name="tasks.transcribe_video")
def transcribe_video(self, job_id: str, video_asset_id: str, config: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    asset_kwargs = _job_asset_kwargs(job_id)
    opts = config or {}
    warnings: list[str] = []

    src_asset, src_path = fetch_asset(video_asset_id)
    if not src_path or not src_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    backend_raw = str(opts.get("backend") or "noop").strip().lower()
    if backend_raw == "whisper":
        backend_raw = "faster_whisper"
    try:
        backend = TranscriptionBackend(backend_raw)
    except ValueError:
        warnings.append(f"Unknown backend '{backend_raw}'; using noop.")
        backend = TranscriptionBackend.NOOP
    if backend == TranscriptionBackend.OPENAI_WHISPER and offline_mode_enabled():
        warnings.append("Offline mode enabled; refusing openai_whisper and using noop.")
        backend = TranscriptionBackend.NOOP

    cfg = TranscriptionConfig(
        backend=backend,
        model=str(opts.get("model") or "whisper-large-v3"),
        language=str(opts.get("language") or "").strip() or None,
        device=str(opts.get("device")) if opts.get("device") else None,
    )
    transcription = _transcribe_media(src_path, cfg, warnings=warnings)
    words = sorted(getattr(transcription, "words", []) or [], key=lambda w: (w.start, w.end))  # type: ignore[attr-defined]
    if not words:
        warnings.append("Transcription returned no words; falling back to noop output.")
        transcription = transcribe_noop(str(src_path), cfg)
        words = sorted(transcription.words or [], key=lambda w: (w.start, w.end))

    transcript_lines = [
        f"{w.start:.3f}\t{w.end:.3f}\t{w.text}".rstrip()
        for w in words
    ]
    transcript_text = "\n".join(transcript_lines) if transcript_lines else "(no transcription words)"
    asset = create_asset(kind="transcription", mime_type="text/plain", suffix=".txt", contents=transcript_text, **asset_kwargs)
    result = {
        "video_asset_id": video_asset_id,
        "status": "transcribed",
        "config": opts,
        "warnings": warnings,
        "output_asset_id": str(asset.id),
        "backend": backend.value,
        "model": cfg.model,
        "word_count": len(words),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.generate_captions")
def generate_captions(self, job_id: str, video_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id)
    asset_kwargs = _job_asset_kwargs(job_id)
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

    default_model = "whisper-1"
    if backend == TranscriptionBackend.FASTER_WHISPER:
        default_model = "whisper-large-v3"
    elif backend == TranscriptionBackend.WHISPER_CPP:
        default_model = "ggml-base.en"
    elif backend == TranscriptionBackend.WHISPER_TIMESTAMPED:
        default_model = "base"

    config = TranscriptionConfig(
        backend=backend,
        model=str(opts.get("model") or default_model),
        language=language,
        device=str(opts.get("device")) if opts.get("device") else None,
    )
    transcription = _transcribe_media(src_path, config, warnings=warnings)
    words = sorted(getattr(transcription, "words", []) or [], key=lambda w: (w.start, w.end))  # type: ignore[attr-defined]
    if not words:
        warnings.append("Transcription returned no words; falling back to noop output.")
        transcription = transcribe_noop(str(src_path), config)
        words = sorted(transcription.words or [], key=lambda w: (w.start, w.end))

    quality_profile = str(opts.get("subtitle_quality_profile") or "balanced").strip().lower()
    profile_defaults = CAPTION_QUALITY_PROFILES.get(quality_profile)
    if profile_defaults is None:
        warnings.append(f"Unknown subtitle_quality_profile '{quality_profile}'; falling back to balanced.")
        quality_profile = "balanced"
        profile_defaults = CAPTION_QUALITY_PROFILES["balanced"]

    grouping = GroupingConfig(
        max_chars_per_line=int(opts.get("max_chars_per_line") or profile_defaults.get("max_chars_per_line") or GroupingConfig.max_chars_per_line),
        max_words_per_line=int(opts.get("max_words_per_line") or profile_defaults.get("max_words_per_line") or GroupingConfig.max_words_per_line),
        max_duration=float(opts.get("max_duration") or profile_defaults.get("max_duration") or GroupingConfig.max_duration),
        max_gap=float(opts.get("max_gap") or profile_defaults.get("max_gap") or GroupingConfig.max_gap),
        max_chars_per_second=float(
            opts.get("max_chars_per_second")
            or profile_defaults.get("max_chars_per_second")
            or GroupingConfig.max_chars_per_second
        ),
        sentence_break_on_punctuation=_coerce_bool_with_default(
            opts.get("sentence_break_on_punctuation"),
            bool(profile_defaults.get("sentence_break_on_punctuation", GroupingConfig.sentence_break_on_punctuation)),
        ),
        sentence_break_min_gap=float(
            opts.get("sentence_break_min_gap")
            or profile_defaults.get("sentence_break_min_gap")
            or GroupingConfig.sentence_break_min_gap
        ),
        repair_overlaps=_coerce_bool_with_default(opts.get("repair_overlaps"), GroupingConfig.repair_overlaps),
    )
    subtitle_lines = group_words(words, grouping)

    speaker_labels = _coerce_bool(opts.get("speaker_labels") or opts.get("enable_speaker_labels") or opts.get("diarize"))
    diarization_backend_raw = str(
        opts.get("diarization_backend") or opts.get("speaker_diarization_backend") or DiarizationBackend.NOOP.value
    ).strip().lower()
    try:
        diarization_backend = DiarizationBackend(diarization_backend_raw)
    except ValueError:
        warnings.append(f"Unknown diarization backend '{diarization_backend_raw}'; using noop.")
        diarization_backend = DiarizationBackend.NOOP

    default_diarization_model = "pyannote/speaker-diarization-3.1"
    if diarization_backend == DiarizationBackend.SPEECHBRAIN:
        default_diarization_model = "speechbrain/spkrec-ecapa-voxceleb"

    diarization_config = DiarizationConfig(
        backend=diarization_backend,
        model=str(opts.get("diarization_model") or default_diarization_model),
        huggingface_token=str(
            opts.get("huggingface_token")
            or opts.get("hf_token")
            or os.getenv("HUGGINGFACE_TOKEN")
            or os.getenv("HF_TOKEN")
            or ""
        ).strip()
        or None,
        min_segment_duration=float(opts.get("min_segment_duration") or 0.0),
    )

    if speaker_labels and diarization_config.backend != DiarizationBackend.NOOP:
        if diarization_config.backend == DiarizationBackend.PYANNOTE and offline_mode_enabled():
            warnings.append("Offline mode enabled; refusing pyannote diarization and continuing without speaker labels.")
        elif diarization_config.backend == DiarizationBackend.SPEECHBRAIN and offline_mode_enabled():
            warnings.append(
                "Offline mode enabled; refusing speechbrain diarization (may download models) and continuing without speaker labels."
            )
        else:
            audio_wav = new_tmp_file(".wav")
            try:
                _extract_audio_wav_for_diarization(src_path, audio_wav)
                segments = diarize_audio(audio_wav, diarization_config)
                subtitle_lines = assign_speakers_to_lines(subtitle_lines, segments)
            except Exception as exc:
                warnings.append(f"Speaker diarization failed; continuing without speaker labels ({exc}).")
            finally:
                try:
                    audio_wav.unlink()
                except FileNotFoundError:
                    pass
                except Exception:  # pragma: no cover - best effort
                    logger.debug("Failed to remove diarization audio tmp: %s", audio_wav)

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

    asset = create_asset(kind="subtitle", mime_type=mime, suffix=suffix, contents=payload, **asset_kwargs)
    result = {
        "video_asset_id": video_asset_id,
        "status": "captions_generated",
        "options": opts,
        "transcription_backend": backend.value,
        "speaker_labels": speaker_labels,
        "diarization_backend": diarization_config.backend.value,
        "diarization_model": diarization_config.model,
        "model": config.model,
        "language": config.language,
        "warnings": warnings,
        "subtitle_quality_profile": quality_profile,
        "output_asset_id": str(asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.translate_subtitles")
def translate_subtitles(self, job_id: str, subtitle_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, subtitle_asset_id=subtitle_asset_id)
    asset_kwargs = _job_asset_kwargs(job_id)
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

    translator_backend = str(opts.get("translator_backend") or opts.get("translator") or "").strip().lower()

    def _build_groq_translator() -> CloudTranslator | None:
        if offline_mode_enabled():
            warnings.append("Offline mode enabled; refusing Groq translator.")
            return None
        client = get_groq_chat_client_from_env()
        if not client:
            warnings.append("GROQ_API_KEY not set; Groq translator unavailable.")
            return None
        model = str(opts.get("groq_model") or os.getenv("GROQ_MODEL") or "llama3-8b-8192").strip()
        if not model:
            model = "llama3-8b-8192"
        warnings.append(f"Using Groq cloud translator model={model}.")
        return CloudTranslator(client=client, model=model)

    translator = None
    if translator_backend in {"noop"}:
        translator = NoOpTranslator()
    elif translator_backend in {"groq", "cloud"}:
        translator = _build_groq_translator() or NoOpTranslator()
    else:
        try:
            translator = LocalTranslator(src_language, target_language)
        except Exception as exc:
            warnings.append(str(exc))
            translator = _build_groq_translator() or NoOpTranslator()

    text = src_path.read_text(encoding="utf-8", errors="replace")
    src_suffix = src_path.suffix.lower()
    if src_suffix == ".vtt":
        try:
            text = to_srt(parse_vtt(text))
        except Exception as exc:
            error = f"Failed to parse VTT subtitles: {exc}"
            update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
            _progress(self, "failed", 1.0, error=error, subtitle_asset_id=subtitle_asset_id)
            return {"subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}
    elif src_suffix != ".srt":
        error = f"Only .srt/.vtt subtitles are supported for translation currently (got {src_path.suffix or 'no extension'})."
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

    asset = create_asset(kind="subtitle", mime_type="text/srt", suffix=".srt", contents=translated, **asset_kwargs)
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


_SHORTS_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "tiktok bold": {
        "font": "Inter",
        "font_size": 48,
        "text_color": "#ffffff",
        "highlight_color": "#facc15",
        "stroke_width": 3,
        "outline_enabled": True,
        "outline_color": "#000000",
        "shadow_enabled": True,
        "shadow_offset": 4,
        "position": "bottom",
    },
    "clean slate": {
        "font": "Inter",
        "font_size": 44,
        "text_color": "#f9fafb",
        "highlight_color": "#34d399",
        "stroke_width": 2,
        "outline_enabled": False,
        "outline_color": "#000000",
        "shadow_enabled": True,
        "shadow_offset": 3,
        "position": "bottom",
    },
    "night runner": {
        "font": "Space Grotesk",
        "font_size": 46,
        "text_color": "#e5e7eb",
        "highlight_color": "#22d3ee",
        "stroke_width": 3,
        "outline_enabled": True,
        "outline_color": "#111827",
        "shadow_enabled": True,
        "shadow_offset": 4,
        "position": "bottom",
    },
}


def _resolve_style_from_options(opts: dict | None) -> dict[str, Any]:
    if not isinstance(opts, dict):
        return dict(_SHORTS_STYLE_PRESETS["tiktok bold"])
    style = opts.get("style")
    if isinstance(style, dict) and style:
        return style
    preset = str(opts.get("style_preset") or "").strip().lower()
    if preset:
        resolved = _SHORTS_STYLE_PRESETS.get(preset)
        if resolved:
            return dict(resolved)
    return dict(_SHORTS_STYLE_PRESETS["tiktok bold"])


def _slice_subtitle_lines(lines: list[SubtitleLine], *, start: float, end: float) -> list[SubtitleLine]:
    """Extract and time-shift subtitle lines so the clip starts at 0s."""
    clip_duration = max(0.0, float(end) - float(start))
    out: list[SubtitleLine] = []
    for line in lines:
        if line.start >= end or line.end <= start:
            continue

        shifted_start = max(0.0, line.start - start)
        shifted_end = min(clip_duration, line.end - start)
        if shifted_end <= shifted_start:
            continue

        shifted_words: list[Word] = []
        for w in line.words or []:
            try:
                ws = max(0.0, float(w.start) - start)
                we = min(clip_duration, float(w.end) - start)
            except Exception:
                continue
            if we <= ws:
                continue
            try:
                shifted_words.append(Word(text=w.text, start=ws, end=we, probability=getattr(w, "probability", None)))
            except Exception:
                continue

        if not shifted_words:
            # Preserve text even when word timings can't be shifted cleanly.
            text = line.text()
            if text:
                try:
                    shifted_words = [Word(text=text, start=shifted_start, end=shifted_end)]
                except Exception:
                    shifted_words = []

        if shifted_words:
            out.append(SubtitleLine(start=shifted_start, end=shifted_end, words=shifted_words, speaker=line.speaker))
    return out


def _render_styled_subtitles_to_file(
    *,
    job_id: str,
    step: str,
    video_path: Path,
    subtitle_path: Path,
    style: dict | None,
    preview_seconds: int | None = None,
) -> Path:
    subtitle_suffix = subtitle_path.suffix.lower()
    if subtitle_suffix not in {".srt", ".vtt", ".ass"}:
        raise ValueError(f"Only .srt/.vtt/.ass subtitles are supported (got {subtitle_path.suffix or 'no extension'}).")

    subtitle_render_path = subtitle_path
    if subtitle_suffix in {".srt", ".vtt"}:
        subtitle_text = subtitle_path.read_text(encoding="utf-8", errors="replace")
        subtitle_lines = parse_srt(subtitle_text) if subtitle_suffix == ".srt" else parse_vtt(subtitle_text)
        karaoke_ass = to_ass_karaoke(subtitle_lines)
        subtitle_render_path = new_tmp_file(".ass")
        subtitle_render_path.write_text(karaoke_ass, encoding="utf-8")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to render styled subtitles")

    style_dict = style if isinstance(style, dict) else {}
    font = str(style_dict.get("font") or "Arial")
    try:
        font_size = int(style_dict.get("font_size") or 48)
    except (TypeError, ValueError):
        font_size = 48

    outline_enabled = _coerce_bool(style_dict.get("outline_enabled", True))
    try:
        stroke_width = int(style_dict.get("stroke_width") or 2)
    except (TypeError, ValueError):
        stroke_width = 2
    outline_width = max(0, stroke_width if outline_enabled else 0)

    shadow_enabled = _coerce_bool(style_dict.get("shadow_enabled", True))
    try:
        shadow_offset = int(style_dict.get("shadow_offset") or 0)
    except (TypeError, ValueError):
        shadow_offset = 0
    shadow_strength = max(0, shadow_offset if shadow_enabled else 0)

    text_color = _hex_to_ass_color(style_dict.get("text_color"), default="&H00FFFFFF")
    highlight_color = _hex_to_ass_color(style_dict.get("highlight_color"), default="&H0000FFFF")
    outline_color = _hex_to_ass_color(style_dict.get("outline_color"), default="&H00000000")

    position = str(style_dict.get("position") or "bottom").strip().lower()
    alignment = 2
    if position == "top":
        alignment = 8
    elif position == "center":
        alignment = 5

    # Commas are escaped as `\,` because ffmpeg uses commas to separate filters.
    force_style = "\\,".join(
        [
            f"Fontname={font}",
            f"Fontsize={font_size}",
            f"PrimaryColour={text_color}",
            f"SecondaryColour={highlight_color}",
            f"OutlineColour={outline_color}",
            "BorderStyle=1",
            f"Outline={outline_width}",
            f"Shadow={shadow_strength}",
            f"Alignment={alignment}",
        ]
    )
    vf = f"subtitles={subtitle_render_path}:force_style={force_style}"

    output_path = new_tmp_file(".mp4")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(video_path)]
    if preview_seconds is not None:
        cmd += ["-t", str(preview_seconds)]
    cmd += [
        "-vf",
        vf,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    _run_ffmpeg_with_retries(
        job_id=job_id,
        step=step,
        fn=lambda: subprocess.run(cmd, check=True, capture_output=True),
    )

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("Styled render failed: output file was not created")
    return output_path


@celery_app.task(bind=True, name="tasks.render_styled_subtitles")
def render_styled_subtitles(self, job_id: str, video_asset_id: str, subtitle_asset_id: str, style: dict | None = None, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
    asset_kwargs = _job_asset_kwargs(job_id)
    opts = options or {}
    raw_preview_seconds = opts.get("preview_seconds")
    try:
        preview_seconds = int(raw_preview_seconds) if raw_preview_seconds is not None else None
    except (TypeError, ValueError):
        preview_seconds = None
    if preview_seconds is not None and preview_seconds <= 0:
        preview_seconds = None

    video_asset, video_path = fetch_asset(video_asset_id)
    subtitle_asset, subtitle_path = fetch_asset(subtitle_asset_id)

    if not video_path or not video_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
        return {"video_asset_id": video_asset_id, "subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    if not subtitle_path or not subtitle_path.exists():
        error = f"Subtitle asset file missing for {subtitle_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
        return {"video_asset_id": video_asset_id, "subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    style_dict = style if isinstance(style, dict) else {}
    try:
        output_path = _render_styled_subtitles_to_file(
            job_id=job_id,
            step="render_styled_subtitles",
            video_path=video_path,
            subtitle_path=subtitle_path,
            style=style_dict,
            preview_seconds=preview_seconds,
        )
    except Exception as exc:
        stderr = ""
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
        error = f"Styled render failed: {stderr[-4000:] or exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, subtitle_asset_id=subtitle_asset_id)
        return {"video_asset_id": video_asset_id, "subtitle_asset_id": subtitle_asset_id, "status": "failed", "error": error}

    mime_type = video_asset.mime_type if video_asset and video_asset.mime_type else "video/mp4"
    asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=output_path, **asset_kwargs)
    result = {
        "video_asset_id": video_asset_id,
        "subtitle_asset_id": subtitle_asset_id,
        "style": style_dict,
        "options": {"preview_seconds": preview_seconds, **opts},
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
    asset_kwargs = _job_asset_kwargs(job_id)
    opts = options or {}
    warnings: list[str] = []
    max_clips = int(opts.get("max_clips") or 3)
    min_duration = float(opts.get("min_duration") or 10.0)
    max_duration = float(opts.get("max_duration") or 60.0)
    use_subtitles = _coerce_bool(opts.get("use_subtitles"))
    trim_silence = _coerce_bool(opts.get("trim_silence"))
    subtitle_asset_id = str(opts.get("subtitle_asset_id") or "").strip()
    style_for_clip = _resolve_style_from_options(opts) if use_subtitles else {}

    subtitle_source_lines: list[SubtitleLine] | None = None
    if use_subtitles and subtitle_asset_id:
        try:
            _subs_asset, subs_path = fetch_asset(subtitle_asset_id)
            if not subs_path or not subs_path.exists():
                warnings.append(f"subtitle_asset_id {subtitle_asset_id} missing on disk; using placeholder subtitles per clip.")
            else:
                subs_text = subs_path.read_text(encoding="utf-8", errors="replace")
                suffix = subs_path.suffix.lower()
                if suffix == ".vtt":
                    subtitle_source_lines = parse_vtt(subs_text)
                elif suffix == ".srt":
                    subtitle_source_lines = parse_srt(subs_text)
                else:
                    warnings.append(f"subtitle_asset_id must be .srt/.vtt for per-clip slicing (got {subs_path.suffix}); using placeholder subtitles per clip.")
        except Exception as exc:
            warnings.append(f"Failed to load subtitle_asset_id {subtitle_asset_id}; using placeholder subtitles per clip ({exc}).")
    elif use_subtitles:
        warnings.append("use_subtitles enabled but no subtitle_asset_id provided; using placeholder subtitles per clip.")

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
    prompt = str(opts.get("prompt") or "").strip()
    if trim_silence:
        try:
            silent = detect_silence(
                src_path,
                noise_db=float(opts.get("silence_noise_db") or -35.0),
                min_silence_duration=float(opts.get("silence_min_duration") or 0.4),
            )

            def _overlap_seconds(start: float, end: float) -> float:
                total = 0.0
                for s, e in silent:
                    total += max(0.0, min(end, e) - max(start, s))
                return total

            for idx, cand in enumerate(candidates):
                if cand.duration <= 0:
                    cand.score = 0.0
                    continue
                ratio = _overlap_seconds(cand.start, cand.end) / cand.duration
                cand.score = max(0.0, 1.0 - ratio) - (idx * 0.001)
                cand.reason = f"silence_ratio={ratio:.3f}"
        except Exception as exc:
            logger.debug("Silence trimming skipped: %s", exc)
            for idx, cand in enumerate(candidates):
                cand.score = 1.0 - (idx * 0.01)
    else:
        for idx, cand in enumerate(candidates):
            cand.score = 1.0 - (idx * 0.01)

    if subtitle_source_lines:
        for cand in candidates:
            parts = [line.text() for line in subtitle_source_lines if line.start < cand.end and line.end > cand.start and line.text()]
            snippet = " ".join(parts).strip()
            cand.snippet = snippet[:800] if snippet else None

    keywords: list[str] = []
    prompt_keywords = [token for token in re.findall(r"[a-z0-9']+", prompt.lower()) if len(token) >= 3]
    keywords.extend(prompt_keywords)
    extra_keywords = opts.get("keywords")
    if isinstance(extra_keywords, list):
        keywords.extend(str(item).strip().lower() for item in extra_keywords if str(item).strip())
    deduped_keywords: list[str] = []
    seen_kw: set[str] = set()
    for keyword in keywords:
        if keyword in seen_kw:
            continue
        seen_kw.add(keyword)
        deduped_keywords.append(keyword)

    weight_overrides = opts.get("segment_scoring_weights")
    if not isinstance(weight_overrides, dict):
        weight_overrides = {}
    legacy_weight_map = {
        "keyword_density_weight": "keyword_density",
        "sentence_boundary_bonus_weight": "sentence_boundary_bonus",
        "speech_density_weight": "speech_density_norm",
        "duration_bonus_weight": "duration_bonus",
        "novelty_penalty_weight": "novelty_penalty",
        "base_score_weight": "base_score",
    }
    for legacy_key, canonical_key in legacy_weight_map.items():
        if legacy_key in opts and canonical_key not in weight_overrides:
            weight_overrides[canonical_key] = opts.get(legacy_key)

    parsed_weight_overrides: dict[str, float] = {}
    if weight_overrides:
        for key, value in weight_overrides.items():
            if key not in HeuristicWeights.__dataclass_fields__:
                continue
            try:
                parsed_weight_overrides[key] = float(value)
            except (TypeError, ValueError):
                continue

    score_segments_heuristic(
        candidates,
        keywords=deduped_keywords,
        weights=HeuristicWeights(**parsed_weight_overrides) if parsed_weight_overrides else None,
    )

    scoring_backend = str(opts.get("segment_scoring_backend") or opts.get("scoring_backend") or "").strip().lower()
    if scoring_backend == "groq":
        if not prompt:
            warnings.append("Groq scoring requested but no prompt was provided; falling back to heuristics.")
        elif offline_mode_enabled():
            warnings.append("Groq scoring requested but offline mode is enabled; falling back to heuristics.")
        elif not subtitle_asset_id:
            warnings.append("Groq scoring requested but no subtitle_asset_id provided; falling back to heuristics.")
        else:
            try:
                _subs_asset, subs_path = fetch_asset(subtitle_asset_id)
                if not subs_path or not subs_path.exists():
                    warnings.append(f"subtitle_asset_id {subtitle_asset_id} missing on disk; falling back to heuristics.")
                else:
                    subs_text = subs_path.read_text(encoding="utf-8", errors="replace")
                    suffix = subs_path.suffix.lower()
                    if suffix == ".vtt":
                        subtitle_lines = parse_vtt(subs_text)
                    elif suffix == ".srt":
                        subtitle_lines = parse_srt(subs_text)
                    else:
                        warnings.append(f"subtitle_asset_id must be .srt/.vtt for Groq scoring (got {subs_path.suffix}); falling back to heuristics.")
                        subtitle_lines = None

                    if not subtitle_lines:
                        raise ValueError("Subtitle parsing failed or unsupported subtitle format.")

                    transcript = "\n".join(l.text() for l in subtitle_lines if l.text())
                    for cand in candidates:
                        parts = [l.text() for l in subtitle_lines if l.start < cand.end and l.end > cand.start and l.text()]
                        snippet = " ".join(parts).strip()
                        cand.snippet = snippet[:800] if snippet else None

                    client = get_groq_chat_client_from_env()
                    if not client:
                        warnings.append("Groq scoring requested but GROQ_API_KEY is not set; falling back to heuristics.")
                    else:
                        model = str(opts.get("groq_model") or os.getenv("GROQ_MODEL") or "llama3-8b-8192").strip()
                        if not model:
                            model = "llama3-8b-8192"

                        base_scores = {(c.start, c.end): float(c.score) for c in candidates}
                        score_prompt = (
                            "You are scoring candidate video segments for creating short clips.\n"
                            f"Goal: {prompt}\n\n"
                            "Return ONLY a JSON array. Each item must be an object:\n"
                            '{\"start\": number, \"end\": number, \"score\": number}\n'
                            "Score each candidate from 0.0 to 1.0 (higher is better)."
                        )
                        score_segments_llm(transcript=transcript, candidates=candidates, prompt=score_prompt, model=model, client=client, provider="groq")
                        # Blend with existing heuristics (e.g., silence trimming) so we still down-rank silent segments.
                        for cand in candidates:
                            base = base_scores.get((cand.start, cand.end), 0.0)
                            cand.score = (0.2 * base) + (0.8 * float(cand.score))
                        warnings.append(f"Applied Groq segment scoring model={model}.")
            except Exception as exc:
                warnings.append(f"Groq scoring failed; falling back to heuristics ({exc}).")

    selected = select_top(
        candidates,
        max_segments=max_clips,
        min_duration=min_duration,
        max_duration=max_duration,
        min_gap=float(opts.get("min_gap") or 0.0),
    )
    if not selected:
        selected = candidates[:max_clips]

    clips: list[dict] = []
    for idx, seg in enumerate(selected):
        update_job(job_id, progress=0.1 + (idx / max(1, len(selected))) * 0.8)
        _progress(self, "processing", idx / max(1, len(selected)), clip_index=idx + 1)

        clip_path = new_tmp_file(".mp4")
        try:
            _run_ffmpeg_with_retries(
                job_id=job_id,
                step=f"cut_clip:{idx + 1}",
                fn=lambda: cut_clip(src_path, seg.start, seg.end, clip_path),
            )
        except Exception as exc:
            error = f"Failed to cut clip {idx + 1}: {exc}"
            update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
            _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
            return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

        mime_type = src_asset.mime_type if src_asset and src_asset.mime_type else "video/mp4"
        clip_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=clip_path, **asset_kwargs)

        thumb_asset = create_thumbnail_asset(clip_path, **asset_kwargs)

        subtitle_asset = None
        styled_asset = None
        clip_style_preset = str(opts.get("style_preset") or "").strip() or None
        if use_subtitles:
            subtitle_file: Path | None = None
            try:
                subtitle_file = new_tmp_file(".vtt")
                if subtitle_source_lines is not None:
                    sliced = _slice_subtitle_lines(subtitle_source_lines, start=seg.start, end=seg.end)
                    subtitle_contents = to_vtt(sliced)
                else:
                    subtitle_contents = (
                        "WEBVTT\n\n"
                        "00:00:00.000 --> 00:00:02.000\n"
                        f"Clip {idx + 1} subtitle placeholder\n"
                    )
                subtitle_file.write_text(subtitle_contents, encoding="utf-8")
                subtitle_asset = create_asset_for_existing_file(
                    kind="subtitle",
                    mime_type="text/vtt",
                    file_path=subtitle_file,
                    **asset_kwargs,
                )
            except Exception as exc:
                warnings.append(f"Clip {idx + 1}: failed to build subtitles ({exc}); continuing without subtitles.")
                subtitle_asset = None
                subtitle_file = None

            if subtitle_file and subtitle_asset:
                try:
                    styled_path = _render_styled_subtitles_to_file(
                        job_id=job_id,
                        step=f"render_shorts_clip:{idx + 1}",
                        video_path=clip_path,
                        subtitle_path=subtitle_file,
                        style=style_for_clip,
                        preview_seconds=None,
                    )
                    styled_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=styled_path, **asset_kwargs)
                except Exception as exc:
                    stderr = ""
                    if isinstance(exc, subprocess.CalledProcessError):
                        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
                    warnings.append(f"Clip {idx + 1}: styled render failed ({stderr[-4000:] or exc}).")
                    styled_asset = None

        clips.append(
            {
                "id": f"{job_id}-clip-{idx + 1}",
                "asset_id": str(clip_asset.id),
                "style_preset": clip_style_preset,
                "start": seg.start,
                "end": seg.end,
                "duration": round(seg.duration, 3),
                "score": seg.score,
                "uri": clip_asset.uri,
                "styled_uri": styled_asset.uri if styled_asset else None,
                "styled_asset_id": str(styled_asset.id) if styled_asset else None,
                "thumbnail_asset_id": str(thumb_asset.id),
                "subtitle_uri": subtitle_asset.uri if subtitle_asset else None,
                "subtitle_asset_id": str(subtitle_asset.id) if subtitle_asset else None,
                "thumbnail_uri": thumb_asset.uri,
            }
        )

    manifest = {
        "video_asset_id": video_asset_id,
        "options": opts,
        "warnings": warnings,
        "clip_assets": clips,
    }
    manifest_asset = create_asset(
        kind="shorts_manifest",
        mime_type="application/json",
        suffix=".json",
        contents=json.dumps(manifest, indent=2),
        **asset_kwargs,
    )

    result = {
        "video_asset_id": video_asset_id,
        "status": "shorts_generated",
        "warnings": warnings,
        "clip_assets": clips,
        "output_asset_id": str(manifest_asset.id),
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload={"clip_assets": clips, "warnings": warnings, **opts}, output_asset_id=str(manifest_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id)
    return result


@celery_app.task(bind=True, name="tasks.cut_clip")
def cut_clip_asset(self, job_id: str, video_asset_id: str, start: float, end: float, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, start=start, end=end)
    asset_kwargs = _job_asset_kwargs(job_id)
    opts = options or {}

    src_asset, src_path = fetch_asset(video_asset_id)
    if not src_path or not src_path.exists():
        error = f"Video asset file missing for {video_asset_id}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    start_s = float(start or 0.0)
    end_s = float(end or start_s)
    if end_s < start_s:
        start_s, end_s = end_s, start_s

    output_path = new_tmp_file(".mp4")
    try:
        _run_ffmpeg_with_retries(
            job_id=job_id,
            step="cut_clip",
            fn=lambda: cut_clip(src_path, start_s, end_s, output_path),
        )
    except Exception as exc:
        error = f"Cut clip failed: {exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, start=start_s, end=end_s)
        return {"video_asset_id": video_asset_id, "status": "failed", "error": error}

    mime_type = src_asset.mime_type if src_asset and src_asset.mime_type else "video/mp4"
    clip_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=output_path, **asset_kwargs)
    thumb_asset = create_thumbnail_asset(output_path, **asset_kwargs)

    result = {
        "video_asset_id": video_asset_id,
        "start": start_s,
        "end": end_s,
        "duration": round(max(0.0, end_s - start_s), 3),
        "asset_id": str(clip_asset.id),
        "uri": clip_asset.uri,
        "thumbnail_asset_id": str(thumb_asset.id),
        "thumbnail_uri": thumb_asset.uri,
        **opts,
    }
    update_job(job_id, status=JobStatus.completed, progress=1.0, payload=result, output_asset_id=str(clip_asset.id))
    _progress(self, "completed", 1.0, video_asset_id=video_asset_id, start=start_s, end=end_s, output_asset_id=str(clip_asset.id))
    return result


@celery_app.task(bind=True, name="tasks.merge_video_audio")
def merge_video_audio(self, job_id: str, video_asset_id: str, audio_asset_id: str, options: dict | None = None) -> dict:
    update_job(job_id, status=JobStatus.running, progress=0.1)
    _progress(self, "started", 0.0, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
    asset_kwargs = _job_asset_kwargs(job_id)
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
        _run_ffmpeg_with_retries(
            job_id=job_id,
            step="merge_video_audio",
            fn=lambda: ffmpeg_merge_video_audio(
                video_path,
                audio_path,
                output_path,
                offset=float(opts.get("offset") or 0.0),
                ducking=opts.get("ducking"),
                normalize=bool(opts.get("normalize", True)),
            ),
        )
    except Exception as exc:
        error = f"Merge failed: {exc}"
        update_job(job_id, status=JobStatus.failed, progress=1.0, error=error)
        _progress(self, "failed", 1.0, error=error, video_asset_id=video_asset_id, audio_asset_id=audio_asset_id)
        return {"video_asset_id": video_asset_id, "audio_asset_id": audio_asset_id, "status": "failed", "error": error}

    mime_type = video_asset.mime_type if video_asset and video_asset.mime_type else "video/mp4"
    merged_asset = create_asset_for_existing_file(kind="video", mime_type=mime_type, file_path=output_path, **asset_kwargs)

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


@celery_app.task(bind=True, name="tasks.cleanup_retention")
def cleanup_retention(self) -> dict:
    _progress(self, "started", 0.0)
    now = datetime.now(timezone.utc)
    cleaned_jobs = 0
    cleaned_assets = 0

    with Session(get_engine()) as session:
        subs = session.exec(select(Subscription)).all()
        plan_by_org: dict[UUID, str] = {sub.org_id: sub.plan_code for sub in subs if sub.org_id}

        terminal_statuses = [JobStatus.completed, JobStatus.failed, JobStatus.cancelled]
        jobs = session.exec(select(Job).where(Job.status.in_(terminal_statuses))).all()
        for idx, job in enumerate(jobs):
            if not job.org_id:
                continue
            plan_code = plan_by_org.get(job.org_id, "free")
            if not _is_older_than_retention(created_at=job.updated_at, plan_code=plan_code, now=now):
                continue

            related_asset_ids = _job_related_asset_ids(job)
            payload = job.payload if isinstance(job.payload, dict) else {}
            payload = {**payload, "retention_cleanup_at": now.isoformat(), "retention_plan_code": plan_code}
            payload.pop("clip_assets", None)
            job.payload = payload
            job.output_asset_id = None
            session.add(job)
            session.flush()

            for asset_id in related_asset_ids:
                asset = session.get(MediaAsset, asset_id)
                if not asset:
                    continue
                if _asset_referenced_by_jobs(session, asset_id):
                    continue
                _delete_asset(session, asset)
                cleaned_assets += 1

            cleaned_jobs += 1
            if jobs:
                _progress(self, "running", min(0.99, (idx + 1) / max(1, len(jobs))))

        session.commit()

    result = {
        "status": "ok",
        "cleaned_jobs": cleaned_jobs,
        "cleaned_assets": cleaned_assets,
        "timestamp": now.isoformat(),
    }
    _progress(self, "completed", 1.0, **result)
    return result


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
