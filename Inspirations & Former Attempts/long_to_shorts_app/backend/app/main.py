import os, uuid, zipfile
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import List
from celery.result import AsyncResult
from app.tasks import process_video

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")
STORAGE = os.getenv("STORAGE_PATH", "/storage")
os.makedirs(STORAGE, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    clips: int = Form(4),
    model: str = Form("whisper-large-v3"),
    target_lang: str = Form(""),
    min_duration: float = Form(None),
    max_duration: float = Form(None),
    burn: bool = Form(False),
):
    video_id = str(uuid.uuid4())
    filename = f"{video_id}_{file.filename}"
    path = os.path.join(STORAGE, filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    job = process_video.delay(
        filename, clips, model, target_lang, min_duration, max_duration, burn
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)
# rest unchanged...
