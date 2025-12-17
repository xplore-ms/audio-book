# backend/main.py
from typing import Optional
import uuid
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import io
from celery import Celery
from datetime import datetime

from supabase_client import upload_bytes, download_to_bytes
from pdf_utils import get_num_pages_from_bytes
from mongo import jobs_collection, ensure_indexes
from dotenv import load_dotenv
load_dotenv()

# ensure mongo indexes
ensure_indexes()

app = FastAPI(title="Stateless PDF → Audio Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

celery = Celery("worker")
celery.config_from_object("celeryconfig")

SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "reading_app")

def make_folder_name(job_id: str) -> str:
    date = datetime.utcnow().strftime("%Y%m%d")
    return f"{date}_{job_id}"


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), email: str = Form(...)):
    """
    Upload PDF and register job with email.
    Prevents uploads > 50MB.
    """

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    # Read the bytes
    pdf_bytes = await file.read()

    # --- Prevent PDF > 50MB ---
    if len(pdf_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"PDF is too large ({len(pdf_bytes) / (1024*1024):.2f} MB). "
                   "Maximum allowed size is 50 MB."
        )

    job_id = str(uuid.uuid4())
    folder_name = make_folder_name(job_id)
    remote_path = f"pdfs/{folder_name}/original.pdf"

    # Upload to Supabase
    upload_bytes(remote_path, pdf_bytes, "application/pdf")

    # Count pages
    num_pages = get_num_pages_from_bytes(pdf_bytes)
    digits = len(str(num_pages))

    # Store metadata
    jobs_collection.insert_one({
        "job_id": job_id,
        "email": email,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits,
        "created_at": datetime.utcnow()
    })

    return {
        "job_id": job_id,
        "folder_name": folder_name,
        "remote_pdf_path": remote_path,
        "num_pages": num_pages,
        "digits": digits
    }

MAX_PAGES = 4

@app.post("/start-job")
def start_job(job_id: str, remote_pdf_path: str, start: int = 1, end: Optional[int] = None):
    job = jobs_collection.find_one({"job_id": job_id})
    if job is None:
        raise HTTPException(404, "Job not found")

    total = job["num_pages"]
    end = end or total

    # Validate range is inside total pages
    if start < 1 or end > total or start > end:
        raise HTTPException(400, "Invalid page range")

    # Count number of pages requested
    pages_requested = end - start + 1

    # Enforce max of 4 pages
    if pages_requested > MAX_PAGES:
        raise HTTPException(
            400, 
            f"You can only process a maximum of {MAX_PAGES} pages at once. "
            f"You requested {pages_requested} pages."
        )

    # Process pages
    task_ids = []
    for page in range(start, end + 1):
        res = celery.send_task("tasks.process_page", args=[job_id, job["remote_pdf_path"], page])
        task_ids.append(res.id)

    return {
        "job_id": job_id,
        "task_ids": task_ids,
        "pages_processing": pages_requested
    }


@app.get("/status/{task_id}")
def get_status(task_id: str):
    async_result = celery.AsyncResult(task_id)
    return {"state": async_result.state, "result": async_result.result}


@app.post("/merge/{job_id}")
def merge(job_id: str):
    job = jobs_collection.find_one({"job_id": job_id})
    if job is None:
        raise HTTPException(404, "Job not found")

    r = celery.send_task("tasks.merge_pages", args=[job_id])
    return {"merge_task_id": r.id}

@app.get("/api/audio/stream")
def stream_audio(token: str):
    job = jobs_collection.find_one({"access_token": token})
    if not job:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    final_parts = job.get("final_parts", [])
    if not final_parts:
        raise HTTPException(status_code=404, detail="Audio not found")

    def extract_storage_path(public_url: str) -> str:
        """
        Converts:
        https://xxx.supabase.co/storage/v1/object/public/reading_app/pdfs/abc.wav

        To:
        pdfs/abc.wav
        """
        marker = f"/storage/v1/object/public/{SUPABASE_BUCKET}/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    def audio_generator():
        for idx, public_url in enumerate(final_parts):
            storage_path = extract_storage_path(public_url)

            audio_bytes = download_to_bytes(storage_path)

            # Strip WAV header for all except first
            if idx > 0:
                audio_bytes = audio_bytes[44:]

            yield audio_bytes

    return StreamingResponse(
        audio_generator(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=audiobook.wav"
        }
    )

@app.get("/api/audio/download")
def download_audio(token: str):
    job = jobs_collection.find_one({"access_token": token})
    if not job:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    final_parts = job.get("final_parts", [])
    if not final_parts:
        raise HTTPException(status_code=404, detail="Audio not found")

    def extract_storage_path(public_url: str) -> str:
        marker = f"/storage/v1/object/public/{SUPABASE_BUCKET}/"
        if marker not in public_url:
            raise RuntimeError("Invalid Supabase public URL format")
        return public_url.split(marker, 1)[1]

    output = io.BytesIO()

    for idx, public_url in enumerate(final_parts):
        storage_path = extract_storage_path(public_url)
        audio_bytes = download_to_bytes(storage_path)

        # Remove WAV header for all except first
        if idx > 0:
            audio_bytes = audio_bytes[44:]

        output.write(audio_bytes)

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=audiobook.wav",
            "Content-Length": str(output.getbuffer().nbytes),
            "Cache-Control": "no-store"
        }
    )
