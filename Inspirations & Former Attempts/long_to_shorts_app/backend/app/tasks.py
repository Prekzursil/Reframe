import os, uuid, subprocess, random, requests, time
from celery import Celery
from googletrans import Translator
from requests.exceptions import ReadTimeout
import pysubs2

broker = os.getenv("CELERY_BROKER_URL")
backend = os.getenv("CELERY_RESULT_BACKEND")
celery = Celery("app.tasks", broker=broker, backend=backend)
STORAGE = os.getenv("STORAGE_PATH", "/storage")
# Support multiple endpoints, comma-separated
ENDPOINTS = os.getenv("GROQ_API_URLS", os.getenv("GROQ_API_URL", "")).split(",")
GROQ_KEY = os.getenv("GROQ_API_KEY")
translator = Translator()

def format_timestamp(sec: float) -> str:
    hrs = int(sec//3600); mins = int((sec%3600)//60)
    secs = int(sec%60); msec = int((sec-int(sec))*1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msec:03d}"

def full_word_transcribe(video_path, model):
    # Extract full audio
    wav_full = video_path.rsplit(".",1)[0] + "_full.wav"
    subprocess.run(["ffmpeg","-y","-i",video_path,"-vn","-ac","1","-ar","16000",wav_full], check=True)
    headers = {"Authorization": f"Bearer {GROQ_KEY}"}
    data = {"model": model, "response_format": "verbose_json", "word_timestamps": True}
    files = {"file": open(wav_full,"rb")}
    last_error = None
    for endpoint in ENDPOINTS:
        try:
            resp = requests.post(endpoint, headers=headers, data=data, files=files, timeout=(10,300))
            resp.raise_for_status()
            job = resp.json()
            break
        except Exception as e:
            last_error = e
            continue
    else:
        raise RuntimeError(f"Full transcription failed: {last_error}")
    words = []
    for seg in job.get("segments", []):
        for w in seg.get("words", []):
            words.append({"start": w["start"], "end": w["end"], "word": w["text"]})
    src_lang = job.get("language")
    return words, src_lang

def chunk_words(words, chunk_size=5):
    chunks = []
    for i in range(0, len(words), chunk_size):
        grp = words[i:i+chunk_size]
        if not grp: continue
        chunk_start = grp[0]["start"]
        chunk_end = grp[-1]["end"]
        chunk_text = " ".join(w["word"] for w in grp)
        chunks.append({"start": chunk_start, "end": chunk_end, "text": chunk_text})
    return chunks

def write_subtitles(chunks, base_path):
    # SRT
    srt_name = base_path + ".srt"
    srt_path = os.path.join(STORAGE, srt_name)
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(chunks, 1):
            f.write(f"{idx}\n{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n{seg['text']}\n\n")
    # ASS
    ass = pysubs2.SSAFile()
    style = pysubs2.SSAStyle()
    style.alignment = 2
    style.primarycolor = "&H00FFFF00"
    style.secondarycolor = "&HFFFFFFFF"
    style.outlinecolor = "&H00000000"
    style.outline = 1
    ass.styles["Default"] = style
    for seg in chunks:
        ass.append(pysubs2.SSAEvent(start=int(seg['start']*1000),
                                     end=int(seg['end']*1000),
                                     text=seg['text'],
                                     style="Default"))
    ass_name = base_path + ".ass"
    ass.save(os.path.join(STORAGE, ass_name))
    return srt_name, ass_name

@celery.task
def process_video(video_filename, num_clips, model, target_lang, min_dur, max_dur, burn):
    vid = os.path.join(STORAGE, video_filename)
    # Full transcription once
    words, src_lang = full_word_transcribe(vid, model)
    # Optional translation of full transcript
    if target_lang and target_lang != src_lang:
        full_text = " ".join(w["word"] for w in words)
        trans_text = translator.translate(full_text, dest=target_lang).text
        trans_words = trans_text.split()
        if len(trans_words) == len(words):
            for i, w in enumerate(words):
                w["word"] = trans_words[i]
    # Split into clips
    out = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",vid],
        capture_output=True, text=True, check=True)
    total = float(out.stdout.strip())
    base_len = total / num_clips
    # apply min/max
    clip_len = max(min_dur or base_len, min(base_len, max_dur or base_len))
    results = []
    for i in range(num_clips):
        start = i * clip_len
        clip_name = f"{uuid.uuid4()}.mp4"
        clip_path = os.path.join(STORAGE, clip_name)
        subprocess.run(
            ["ffmpeg","-y","-i",vid,"-ss",str(start),"-t",str(clip_len),"-c","copy",clip_path],
            check=True)
        # select words for clip and adjust timing
        seg_words = [ {"start": w["start"] - start, "end": w["end"] - start, "word": w["word"]}
                      for w in words if start <= w["start"] < start + clip_len ]
        chunks = chunk_words(seg_words)
        base = clip_path.rsplit(".",1)[0]
        srt, ass = write_subtitles(chunks, base)
        outclip = clip_name
        if burn:
            burned = base + "_burn.mp4"
            subprocess.run(
                ["ffmpeg","-y","-i",clip_path,"-vf",f"subtitles={os.path.join(STORAGE,ass)}",burned],
                check=True)
            outclip = os.path.basename(burned)
        score = round(random.uniform(30,100),2)
        results.append({"clip":outclip,"srt":srt,"ass":ass,"score":score})
    return results
