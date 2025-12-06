import os
import uuid
import subprocess
import random
import requests
import time
from celery import Celery
from googletrans import Translator
from requests.exceptions import ReadTimeout

broker = os.getenv("CELERY_BROKER_URL")
backend = os.getenv("CELERY_RESULT_BACKEND")
celery = Celery("app.tasks", broker=broker, backend=backend)

STORAGE = os.getenv("STORAGE_PATH", "/storage")
GROQ_URL = os.getenv("GROQ_API_URL")
GROQ_KEY = os.getenv("GROQ_API_KEY")

translator = Translator()

def format_timestamp(sec: float) -> str:
    hrs = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    secs = int(sec % 60)
    msec = int((sec - int(sec)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msec:03d}"

def transcribe_and_srt(clip_path: str, model: str, target_lang: str = None) -> str:
    # extract mono WAV @16kHz
    wav = clip_path.rsplit(".", 1)[0] + ".wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", clip_path,
        "-vn", "-ac", "1", "-ar", "16000", wav
    ], check=True)

    headers = {"Authorization": f"Bearer {GROQ_KEY}"}
    data = {"model": model, "response_format": "verbose_json"}
    files = {"file": open(wav, "rb")}

    max_retries = 5
    last_error = None
    for attempt in range(max_retries):
        try:
            # increase read timeout to 300s
            resp = requests.post(GROQ_URL, headers=headers, data=data, files=files, timeout=(10, 300))
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("retry-after", "1"))
                time.sleep(retry_after)
                continue
            if resp.status_code == 520:
                time.sleep(1)
                continue
            resp.raise_for_status()
            job = resp.json()
            break
        except ReadTimeout as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            else:
                raise RuntimeError(f"Transcription timed out after retries: {e}")
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                raise RuntimeError(f"Transcription failed: {e}")
    else:
        raise RuntimeError(f"Transcription unrecoverable: {last_error}")

    segments = job.get("segments") or [{"start":0, "end":0, "text": job.get("text", "")}]
    src_lang = job.get("language", None)

    if target_lang and target_lang != src_lang:
        for seg in segments:
            seg["text"] = translator.translate(seg["text"], dest=target_lang).text

    srt_name = os.path.basename(clip_path).rsplit(".",1)[0] + ".srt"
    srt_path = os.path.join(STORAGE, srt_name)
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n")
            f.write(seg["text"].strip() + "\n\n")
    return srt_name

def score_clip(clip_path: str) -> float:
    return round(random.uniform(30, 100), 2)

@celery.task
def process_video(video_filename: str, num_clips: int, model: str, target_lang: str, burn: bool):
    vid = os.path.join(STORAGE, video_filename)
    out = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", vid
    ], capture_output=True, text=True, check=True)
    total = float(out.stdout.strip())
    seg_len = total / num_clips

    results = []
    for i in range(num_clips):
        start = i * seg_len
        clip_name = f"{uuid.uuid4()}.mp4"
        clip_path = os.path.join(STORAGE, clip_name)
        subprocess.run([
            "ffmpeg", "-y", "-i", vid,
            "-ss", str(start), "-t", str(seg_len),
            "-c", "copy", clip_path
        ], check=True)

        srt = transcribe_and_srt(clip_path, model, target_lang)
        if burn:
            burned = clip_path.rsplit(".",1)[0] + "_burn.mp4"
            style = ("FontName=Arial,FontSize=36,"
                     "PrimaryColour=&H00FFFFFF,BackColour=&H80FFFF00,"
                     "BorderStyle=3,Outline=1,OutlineColour=&H00000000")
            vf = f"subtitles={os.path.join(STORAGE, srt)}:force_style='{style}'"
            subprocess.run([
                "ffmpeg", "-y", "-i", clip_path,
                "-vf", vf, burned
            ], check=True)
            clip_name = os.path.basename(burned)

        score = score_clip(clip_path)
        results.append({"clip": clip_name, "srt": srt, "score": score})

    return results
