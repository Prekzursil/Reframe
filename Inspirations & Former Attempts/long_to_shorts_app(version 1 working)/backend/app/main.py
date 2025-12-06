import os
import uuid
import zipfile
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
    model: str = Form("whisper-large"),
    target_lang: str = Form(""),
    burn: bool = Form(False),
):
    video_id = str(uuid.uuid4())
    filename = f"{video_id}_{file.filename}"
    path = os.path.join(STORAGE, filename)
    with open(path, "wb") as f:
        f.write(await file.read())

    job = process_video.delay(
        filename, clips, model, target_lang, burn
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str):
    res = AsyncResult(job_id)
    if res.state in ("PENDING", "STARTED"):
        return templates.TemplateResponse(
            "status.html",
            {"request": request, "job_id": job_id, "status": res.state},
        )
    elif res.state == "SUCCESS":
        results = res.result
        return templates.TemplateResponse(
            "results.html", {"request": request, "results": results}
        )
    elif res.state == "FAILURE":
        error_msg = str(res.result)
        tb = res.traceback or ""
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "job_id": job_id, "error_msg": error_msg, "traceback": tb},
            status_code=500,
        )
    else:
        return templates.TemplateResponse(
            "status.html",
            {"request": request, "job_id": job_id, "status": res.state},
        )

@app.post("/download-zip")
async def download_zip(files: List[str] = Form(...)):
    zip_id = str(uuid.uuid4())
    zip_name = f"{zip_id}.zip"
    zip_path = os.path.join(STORAGE, zip_name)
    with zipfile.ZipFile(zip_path, "w") as z:
        for fname in files:
            z.write(os.path.join(STORAGE, fname), arcname=fname)
    return FileResponse(zip_path, filename=zip_name)

@app.get("/clip/{fname}")
async def clip(fname: str):
    return FileResponse(os.path.join(STORAGE, fname), media_type="video/mp4")

@app.get("/download/{fname}")
async def download(fname: str):
    return FileResponse(os.path.join(STORAGE, fname), filename=fname)
